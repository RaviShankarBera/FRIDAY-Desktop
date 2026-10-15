import os
import time
from pathlib import Path

import pytest

from core import doctor as dr
from core import interactive


def _mk(p: Path, data: bytes, age_days: float = 0):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    if age_days:
        t = time.time() - age_days * 86400
        os.utime(p, (t, t))
    return p


def test_duplicates_are_real_only(tmp_path):
    big = os.urandom(300_000)
    _mk(tmp_path / "a/orig.bin", big, age_days=10)
    _mk(tmp_path / "b/copy.bin", big, age_days=1)
    _mk(tmp_path / "c/copy2.bin", big)
    same_size_diff = bytearray(big); same_size_diff[-1] ^= 1            # differs only at the very end
    _mk(tmp_path / "d/almost.bin", bytes(same_size_diff))
    _mk(tmp_path / "e/small.bin", b"x" * 10)
    _mk(tmp_path / "e/small2.bin", b"x" * 10)
    _mk(tmp_path / "node_modules/x/dup.bin", big)                        # protected folder ignored
    r = dr.find_duplicates([tmp_path], min_bytes=1000)
    assert len(r["groups"]) == 1
    g = r["groups"][0]
    assert g["keep"].endswith("orig.bin") and len(g["dupes"]) == 2
    assert not any("almost" in d or "node_modules" in d for d in g["dupes"])
    assert r["wasted"] == 600_000


def test_apply_duplicates_reverifies_and_uses_trash(tmp_path):
    data = os.urandom(5000)
    k, d1, d2 = _mk(tmp_path / "k.bin", data, 5), _mk(tmp_path / "d1.bin", data), _mk(tmp_path / "d2.bin", data)
    groups = [{"size": 5000, "keep": str(k), "dupes": [str(d1), str(d2)]}]
    d2.write_bytes(b"changed after scan")                                # no longer a duplicate
    trashed = []
    n, freed, errs = dr.apply_duplicates(groups, lambda p: (trashed.append(p), os.remove(p)))
    assert n == 1 and trashed == [str(d1)] and k.exists() and d2.exists() and len(errs) == 1


def test_temp_scan_and_apply_stay_inside_roots(tmp_path):
    root = tmp_path / "Temp"
    _mk(root / "old.tmp", b"x" * 100, 5)
    _mk(root / "sub/older.tmp", b"y" * 200, 9)
    _mk(root / "fresh.tmp", b"z" * 50, 0)
    outside = _mk(tmp_path / "keepme.txt", b"important", 30)
    res = dr.scan_temp([root])
    names = {Path(f).name for f, _ in res["files"]}
    assert names == {"old.tmp", "older.tmp"} and res["total"] == 300
    n, freed, errs = dr.apply_temp(res["files"] + [(str(outside), 9)], [root])
    assert n == 2 and freed == 300 and outside.exists() and (root / "fresh.tmp").exists() and root.exists()
    assert any("outside" in e for e in errs)


def test_folder_sizes(tmp_path):
    _mk(tmp_path / "big/a.bin", b"x" * 5000)
    _mk(tmp_path / "small/b.bin", b"x" * 10)
    _mk(tmp_path / "loose.bin", b"x" * 7)
    r = dr.folder_sizes(tmp_path)
    assert r["folders"][0] == ("big", 5000) and r["loose"] == 7 and not r["partial"]
    assert r["files"][0][0] == 5000


def test_startup_classification():
    assert dr.classify_startup("Spotify")[0] == "disable"
    assert dr.classify_startup("SecurityHealth")[0] == "keep"
    assert dr.classify_startup("RealtekAudio")[0] == "keep"
    assert dr.classify_startup("MyTool")[0] == "review"
    assert dr.list_startup() == []                         # Linux: nothing to read
    assert dr.set_startup_state({"can_disable": True, "where": "HKCU", "name": "x"}, False) is False
    assert dr.DISABLED_BYTES[0] == 3 and dr.ENABLED_BYTES[0] == 2


def test_performance_snapshot_and_verdicts():
    s = dr.performance_snapshot()
    assert 0 <= s["ram_pct"] <= 100 and s["cores"] >= 1 and s["top_mem"]
    assert dr.verdicts({"ram_pct": 95, "cpu_pct": 10, "disks": [{"mount": "C:", "pct": 95, "free": 5 << 30}], "uptime_h": 24 * 10})
    assert "healthy" in dr.verdicts({"ram_pct": 20, "cpu_pct": 5, "disks": [], "uptime_h": 3})[0]


def test_suspicious_heuristics(tmp_path):
    _mk(tmp_path / "Downloads/invoice.pdf.exe", b"MZ")
    _mk(tmp_path / "Downloads/holiday.jpg", b"ok")
    _mk(tmp_path / "Downloads/setup_vlc.exe", b"MZ")
    _mk(tmp_path / "Temp/svchost.exe", b"MZ")
    _mk(tmp_path / "Temp/xkqzjtrwvnbp.exe", b"MZ")
    _mk(tmp_path / "Documents/report.docx", b"ok")
    hits = {Path(h["path"]).name: h for h in dr.scan_suspicious([tmp_path], signer=lambda p: "NotSigned")}
    assert "invoice.pdf.exe" in hits and "double extension" in hits["invoice.pdf.exe"]["why"][0]
    assert "svchost.exe" in hits and any("system file" in w for w in hits["svchost.exe"]["why"])
    assert "xkqzjtrwvnbp.exe" in hits and any("signed" in w for w in hits["xkqzjtrwvnbp.exe"]["why"])
    assert "holiday.jpg" not in hits and "report.docx" not in hits
    assert "not antivirus" in dr.CAVEAT


def test_actions_report_first_and_gate(tmp_path, monkeypatch):
    from actions import system_doctor as sd
    interactive.reset()
    monkeypatch.setattr(sd, "REPORT_DIR", tmp_path / "reports")
    data = os.urandom(3000)
    _mk(tmp_path / "x/a.bin", data, 4); _mk(tmp_path / "x/b.bin", data)
    r = sd.system_doctor({"action": "duplicates", "path": str(tmp_path / "x"), "min_mb": "0.001"})
    assert "Nothing was changed" in r and (tmp_path / "x/b.bin").exists() and list((tmp_path / "reports").glob("duplicates_*.txt"))
    trashed = []
    import send2trash
    monkeypatch.setattr(send2trash, "send2trash", lambda p: (trashed.append(p), os.remove(p)))
    g = sd.system_doctor({"action": "delete_duplicates", "path": str(tmp_path / "x"), "min_mb": "0.001"})
    assert g.startswith("[CONFIRM]") and "1 duplicate files" in g and not trashed
    sk = sd.system_doctor({"action": "delete_duplicates", "path": str(tmp_path / "x"), "min_mb": "0.001", "confirmed": "true"})
    assert sk.startswith("Moved 1") and len(trashed) == 1
    # temp cleanup is gated too
    root = tmp_path / "T"; _mk(root / "o.tmp", b"x" * 99, 9)
    monkeypatch.setattr(dr, "temp_roots", lambda: [root])
    assert "Nothing was deleted" in sd.system_doctor({"action": "temp_report"})
    assert sd.system_doctor({"action": "clean_temp"}).startswith("[CONFIRM]") and (root / "o.tmp").exists()
    assert sd.system_doctor({"action": "clean_temp", "confirmed": "true"}).startswith("Deleted 1")
    assert not (root / "o.tmp").exists()
    assert sd.system_doctor({"action": "bogus"}).startswith("[NEED_INFO]")
    assert "CPU" in sd.system_doctor({"action": "performance"})
    assert "Windows" in sd.system_doctor({"action": "defender_scan"})
    du = sd.system_doctor({"action": "disk_usage", "path": str(tmp_path / "x")})
    assert "free of" in du and "Biggest folders" in du
