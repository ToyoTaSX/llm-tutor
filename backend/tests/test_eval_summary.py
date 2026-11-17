"""Сводка по размеченным результатам прогона (spec quality-eval)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import eval as ev  # noqa: E402

CSV = (
    "id;type;question;reference;mode;web_status;t_mcp;t_total;correct;citation_ok;abstained\n"
    "1;course;q;r;web;ok;2.00;5.00;1;1;\n"
    "2;course;q;r;web;ok;4.00;7.00;0,5;1;\n"
    "3;web;q;r;web;timeout;10.00;12.00;0;0;\n"
    "4;web;q;r;web;ok;3.00;6.00;1;1;\n"
    "5;trap;q;r;web;empty;1.00;4.00;1;1;1\n"
    "6;trap;q;r;web;ok;2.00;5.00;0;0;0\n"
)


def test_summarize(tmp_path):
    p = tmp_path / "r.csv"
    p.write_bytes(CSV.encode("utf-8-sig"))
    s = ev.summarize_rows(ev.read_csv(p))
    assert s["mode"] == "web" and s["n"] == 6
    assert s["acc_all"] == (1 + 0.5 + 0 + 1 + 1 + 0) / 6
    assert s["acc_course"] == 0.75 and s["acc_web"] == 0.5
    assert (s["traps_passed"], s["traps_total"]) == (1, 2)
    assert s["citation_ok_share"] == 4 / 6
    assert s["avg_t_mcp"] == 22 / 6 and s["avg_t_total"] == 39 / 6
    assert s["mcp_statuses"] == {"ok": 4, "timeout": 1, "empty": 1}


def test_summarize_unlabeled(tmp_path):
    p = tmp_path / "r.csv"
    p.write_text("id;type;question;reference;mode;t_total;correct\n1;course;q;r;course;3.00;\n", encoding="utf-8")
    s = ev.summarize_rows(ev.read_csv(p))
    assert s["acc_all"] is None and s["avg_t_mcp"] is None and s["avg_t_total"] == 3.0


def test_questions_web_set():
    rows = ev.read_questions(Path(__file__).resolve().parents[1] / "scripts" / "questions_web.csv")
    assert len(rows) == 12
    types = [r["type"] for r in rows]
    assert {t: types.count(t) for t in set(types)} == {"course": 4, "web": 4, "multi": 2, "trap": 2}
    for r in rows:
        assert r["reference"].strip() and r["allowed_sources"].strip() and r["checked_at"].strip()
