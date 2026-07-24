"""Adversarial durability tests for the Phase-8 JSONL outbox."""
import json
import math
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "lane_node")))

import diag_events as de
from cam_telemetry import CycleShipper


def _row(seq, **extra):
    row = {
        "lane_id": 21,
        "severity": "info",
        "event_type": "recovered",
        "source_id": "hardening",
        "boot_id": "boot",
        "seq": seq,
    }
    row.update(extra)
    return row


def _write_rows(directory, rows, name="diag-20260723.jsonl"):
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, name)
    with open(path, "a", encoding="utf-8") as handle:
        for row in rows:
            if isinstance(row, str):
                handle.write(row + "\n")
            else:
                handle.write(json.dumps(row) + "\n")
    return path


def _event_ack(payload, *, accepted=None, duplicates=0, rejected=None,
               ok=True):
    rejected = [] if rejected is None else rejected
    if accepted is None:
        accepted = len(payload["events"]) - duplicates - len(rejected)
    return {
        "ok": ok,
        "accepted": accepted,
        "inserted": accepted,
        "duplicates": duplicates,
        "rejected": rejected,
    }


def test_cursor_never_advances_on_incomplete_or_false_ack():
    bad_responses = [
        None,
        {"ok": False, "accepted": 1, "inserted": 1,
         "duplicates": 0, "rejected": []},
        {"ok": True, "accepted": 0, "inserted": 0,
         "duplicates": 0, "rejected": []},
        {"ok": True, "accepted": 1, "inserted": 1,
         "duplicates": 0, "rejected": [{"index": 0, "error": "double"}]},
        {"ok": True, "accepted": 0, "inserted": 0,
         "duplicates": 0,
         "rejected": [{"index": 9, "error": "out of range"}]},
    ]
    for response in bad_responses:
        directory = tempfile.mkdtemp(prefix="ack_strict_")
        _write_rows(directory, [_row(1)])
        rep = de.OutboxReplayer(
            directory, "http://unused", post=lambda _u, _p, r=response: r)
        assert rep.replay_once() == 0
        assert not os.path.exists(rep.cursor_path), response
        assert rep.post_errors == 1


def test_duplicate_is_a_complete_ack_disposition():
    directory = tempfile.mkdtemp(prefix="ack_duplicate_")
    _write_rows(directory, [_row(1)])
    rep = de.OutboxReplayer(
        directory, "http://unused",
        post=lambda _u, p: _event_ack(p, accepted=0, duplicates=1))
    assert rep.replay_once() == 1
    assert rep.shipped == 1
    assert rep.replay_once() == 0


def test_out_of_bounds_and_midline_cursors_reset_oldest_first():
    for bad_pos in (3, 999999):
        directory = tempfile.mkdtemp(prefix="cursor_invalid_")
        path = _write_rows(directory, [_row(1), _row(2)])
        name = os.path.basename(path)
        with open(os.path.join(directory, de.CURSOR_FILENAME), "w",
                  encoding="utf-8") as handle:
            json.dump({"file": name, "pos": bad_pos}, handle)
        seen = []

        def post(_url, payload):
            seen.extend(r["seq"] for r in payload["events"])
            return _event_ack(payload)

        rep = de.OutboxReplayer(directory, "http://unused", post=post)
        assert rep.health()["cursor_ok"] is False
        assert rep.replay_once() == 2
        assert seen == [1, 2]
        assert rep.cursor_errors == 1 and rep.cursor_resets == 1
        assert rep.health()["cursor_ok"] is True


def test_corrupt_complete_row_is_quarantined_before_following_event():
    directory = tempfile.mkdtemp(prefix="corrupt_row_")
    _write_rows(directory, ['{"bad":NaN}', _row(2)])
    seen = []

    def post(_url, payload):
        seen.extend(r["seq"] for r in payload["events"])
        return _event_ack(payload)

    rep = de.OutboxReplayer(directory, "http://unused", post=post)
    assert rep.replay_once() == 1
    assert seen == [2]
    assert rep.corrupt_rows == 1
    assert rep.quarantined == 1
    with open(rep.quarantine_path, encoding="utf-8") as handle:
        quarantine = [json.loads(line) for line in handle if line.strip()]
    assert quarantine[0]["reason"] == "corrupt_json"
    assert rep.replay_once() == 0


def test_corrupt_row_is_not_consumed_if_quarantine_write_fails():
    directory = tempfile.mkdtemp(prefix="corrupt_blocked_")
    _write_rows(directory, ['{"bad":NaN}', _row(2)])
    calls = []
    rep = de.OutboxReplayer(
        directory, "http://unused",
        post=lambda _u, p: calls.append(p) or _event_ack(p))
    # Inject only the replay-time evidence-write failure this test names.
    # Creating the directory before construction also makes startup evidence
    # restoration fail, correctly accounting for a second, distinct error.
    os.makedirs(os.path.join(directory, de.QUARANTINE_FILENAME))
    assert rep.replay_once() == 0
    assert calls == []
    with open(rep.cursor_path, encoding="utf-8") as handle:
        assert json.load(handle)["pos"] == 0
    assert rep.quarantine_errors == 1


def test_unreadable_quarantine_artifact_is_counted_during_restore():
    directory = tempfile.mkdtemp(prefix="quarantine_restore_blocked_")
    os.makedirs(os.path.join(directory, de.QUARANTINE_FILENAME))

    rep = de.OutboxReplayer(directory, "http://unused")

    assert rep.quarantine_errors == 1
    assert rep.errors == 1


def test_rejected_row_is_not_acknowledged_if_quarantine_fsync_fails(
        monkeypatch):
    directory = tempfile.mkdtemp(prefix="quarantine_fsync_")
    _write_rows(directory, [_row(1)])

    def reject(_url, payload):
        return _event_ack(
            payload, accepted=0,
            rejected=[{"index": 0, "error": "forced poison"}])

    rep = de.OutboxReplayer(directory, "http://unused", post=reject)
    monkeypatch.setattr(de.os, "fsync", lambda _fd: (_ for _ in ()).throw(
        OSError("forced fsync failure")))
    assert rep.replay_once() == 0
    assert rep.quarantine_errors == 1
    assert rep.quarantined == 0
    assert not os.path.exists(rep.cursor_path)


def test_jsonl_batch_remains_pending_when_durability_barrier_fails(
        tmp_path, monkeypatch):
    sink = de.JsonlSink(
        str(tmp_path), flush_n=2, flush_s=999,
        today=lambda: "20260723")
    assert sink.emit({"lane_id": 21}) is True
    monkeypatch.setattr(de.os, "fsync", lambda _fd: (_ for _ in ()).throw(
        OSError("forced fsync failure")))

    assert sink.flush() is False
    assert sink.pending_writes == 1
    assert sink.write_errors >= 1
    assert sink.retry_batches >= 1


def test_cursor_save_reports_fsync_failure(tmp_path, monkeypatch):
    rep = de.OutboxReplayer(
        str(tmp_path), "http://unused",
        post=lambda *_args, **_kwargs: {})
    monkeypatch.setattr(de.os, "fsync", lambda _fd: (_ for _ in ()).throw(
        OSError("forced fsync failure")))

    assert rep._save_cursor(
        {"file": "diag-20260723.jsonl", "pos": 0}) is False
    assert rep.cursor_errors == 1


def test_cycle_rejection_is_quarantined_without_poisoning_later_rows():
    directory = tempfile.mkdtemp(prefix="cycle_poison_")
    cycle_bad = _row(1, _kind="cycle", final_state="NOT_A_STATE")
    cycle_good = _row(2, _kind="cycle", final_state="READY")
    event = _row(3)
    _write_rows(directory, [cycle_bad, cycle_good, event])
    cycle_calls = {"n": 0}
    event_seen = []

    def post(url, payload):
        if url.endswith("/cycles"):
            cycle_calls["n"] += 1
            if cycle_calls["n"] == 1:
                return {
                    "ok": True, "accepted": 0, "duplicates": 0,
                    "rejected": [{"index": 0, "error": "bad final_state"}],
                    "id": None,
                }
            return {"ok": True, "accepted": 1, "duplicates": 0,
                    "rejected": [], "id": 7}
        event_seen.extend(r["seq"] for r in payload["events"])
        return _event_ack(payload)

    rep = de.OutboxReplayer(directory, "http://unused", post=post)
    assert rep.replay_once() == 3
    assert cycle_calls["n"] == 2 and event_seen == [3]
    assert rep.cycles_quarantined == 1
    assert rep.cycles_shipped == 1
    assert rep.replay_once() == 0


def test_cycle_retryable_failure_keeps_cursor_and_later_rows_unconsumed():
    directory = tempfile.mkdtemp(prefix="cycle_retry_")
    _write_rows(directory, [
        _row(1, _kind="cycle", final_state="READY"),
        _row(2),
    ])
    calls = []

    def post(url, payload):
        calls.append(url)
        return {"_http_status": 503, "ok": False}

    rep = de.OutboxReplayer(directory, "http://unused", post=post)
    assert rep.replay_once() == 0
    assert calls == ["http://unused/api/machine/cycles"]
    assert not os.path.exists(rep.cursor_path)


def test_jsonl_retries_oldest_failed_batch_and_never_writes_nan():
    root = tempfile.mkdtemp(prefix="sink_retry_")
    directory = os.path.join(root, "blocked")
    with open(directory, "w", encoding="utf-8") as handle:
        handle.write("not a directory")
    sink = de.JsonlSink(directory, flush_n=2, today=lambda: "20260723")
    sink.emit({"seq": 1, "value": math.nan})
    sink.emit({"seq": 2, "value": math.inf})
    assert sink.write_errors == 1
    assert sink.pending_writes == 2

    os.unlink(directory)
    os.makedirs(directory)
    assert sink.flush() is True
    assert sink.pending_writes == 0
    with open(os.path.join(directory, "diag-20260723.jsonl"),
              encoding="utf-8") as handle:
        raw = handle.read()
    rows = [json.loads(line) for line in raw.splitlines()]
    assert [row["seq"] for row in rows] == [1, 2]
    assert [row["value"] for row in rows] == [None, None]
    assert "NaN" not in raw and "Infinity" not in raw


def test_jsonl_failed_batch_is_bounded_and_new_drop_is_observable():
    root = tempfile.mkdtemp(prefix="sink_bound_")
    blocker = os.path.join(root, "blocked")
    with open(blocker, "w", encoding="utf-8") as handle:
        handle.write("not a directory")
    sink = de.JsonlSink(blocker, flush_n=1)
    assert sink.emit({"seq": 1}) is True
    assert sink.emit({"seq": 2}) is False
    assert sink.pending_writes == 1
    assert sink.dropped == 1
    assert sink.retry_batches >= 2


def test_jsonl_seals_crash_partial_before_appending_next_record():
    directory = tempfile.mkdtemp(prefix="sink_partial_")
    path = os.path.join(directory, "diag-20260723.jsonl")
    with open(path, "wb") as handle:
        handle.write(b'{"partial":')
    sink = de.JsonlSink(
        directory, flush_n=1, today=lambda: "20260723")
    assert sink.repaired_tails == 1
    sink.emit(_row(2))
    with open(path, "rb") as handle:
        lines = handle.read().splitlines()
    assert lines[0] == b'{"partial":'
    assert json.loads(lines[1])["seq"] == 2


def test_rollover_repairs_old_partial_tail_and_reaches_newer_file():
    directory = tempfile.mkdtemp(prefix="rollover_partial_")
    day = {"value": "20260722"}
    sink = de.JsonlSink(
        directory, flush_n=1, today=lambda: day["value"])
    old_path = os.path.join(directory, "diag-20260722.jsonl")
    with open(old_path, "wb") as handle:
        handle.write((json.dumps(_row(1)) + "\n").encode("utf-8"))
        handle.write(b'{"crash_torn":')

    # The writer has rolled to a new UTC day. Its append lock/current-day
    # proof now makes the old tail safe to seal.
    day["value"] = "20260723"
    assert sink.emit(_row(2)) is True
    seen = []

    def post(_url, payload):
        seen.extend(row["seq"] for row in payload["events"])
        return _event_ack(payload)

    rep = de.OutboxReplayer(
        directory, "http://unused", post=post, sink=sink)
    assert rep.replay_once() == 2
    assert seen == [1, 2]
    assert sink.repaired_tails == 1
    assert rep.corrupt_rows == 1
    assert rep.quarantined == 1
    with open(old_path, "rb") as handle:
        assert handle.read().endswith(b"\n")
    with open(rep.cursor_path, encoding="utf-8") as handle:
        assert json.load(handle)["file"] == "diag-20260723.jsonl"


def test_replayer_never_seals_the_sink_current_file():
    directory = tempfile.mkdtemp(prefix="active_partial_")
    sink = de.JsonlSink(
        directory, flush_n=1, today=lambda: "20260722")
    active_path = os.path.join(directory, "diag-20260722.jsonl")
    with open(active_path, "wb") as handle:
        handle.write(b'{"append_may_be_in_progress":')
    _write_rows(directory, [_row(2)], name="diag-20260723.jsonl")
    calls = []
    rep = de.OutboxReplayer(
        directory, "http://unused",
        post=lambda _u, p: calls.append(p) or _event_ack(p),
        sink=sink)

    assert rep.replay_once() == 0
    assert calls == []
    assert sink.repaired_tails == 0
    with open(active_path, "rb") as handle:
        assert not handle.read().endswith(b"\n")


def test_outbox_retention_never_prunes_files_without_cursor_proof():
    directory = tempfile.mkdtemp(prefix="retention_proof_")
    day = {"value": "20260721"}
    sink = de.JsonlSink(
        directory, max_files=2, flush_n=1,
        today=lambda: day["value"])
    # Linking the sink to a replayer enables acknowledgement-aware retention.
    de.OutboxReplayer(directory, "http://unused", sink=sink)
    for value in ("20260721", "20260722", "20260723"):
        day["value"] = value
        sink.emit(_row(int(value[-2:])))
    names = sorted(name for name in os.listdir(directory)
                   if name.startswith("diag-"))
    assert names == [
        "diag-20260721.jsonl",
        "diag-20260722.jsonl",
        "diag-20260723.jsonl",
    ]
    assert sink.prune_deferred >= 1

    # Merely naming a newer file is not proof: an out-of-bounds/mid-record
    # cursor must remain fail-closed for retention too.
    with open(os.path.join(directory, de.CURSOR_FILENAME), "w",
              encoding="utf-8") as handle:
        json.dump({"file": "diag-20260723.jsonl", "pos": 999999}, handle)
    sink._prune()
    assert len([name for name in os.listdir(directory)
                if name.startswith("diag-")]) == 3

    # A cursor at the newest file proves the older files are fully resolved;
    # ordinary max_files pruning may now remove only the safe oldest file.
    with open(os.path.join(directory, de.CURSOR_FILENAME), "w",
              encoding="utf-8") as handle:
        json.dump({"file": "diag-20260723.jsonl", "pos": 0}, handle)
    sink._prune()
    names = sorted(name for name in os.listdir(directory)
                   if name.startswith("diag-"))
    assert names == ["diag-20260722.jsonl", "diag-20260723.jsonl"]


def test_outbox_health_has_stable_persistence_and_cursor_fields():
    directory = tempfile.mkdtemp(prefix="health_fields_")
    _write_rows(directory, [_row(1)])
    sink = de.JsonlSink(directory, flush_n=2)
    sink.write_errors = 2
    sink.dropped = 3
    sink._buf.append(_row(99))
    rep = de.OutboxReplayer(directory, "http://unused", sink=sink)
    health = rep.health()
    required = {
        "oldest_unsent_age_s", "backlog", "backlog_bytes", "cursor_ok",
        "quarantined", "corrupt_rows", "skipped", "shipped",
        "cycles_shipped", "cycles_quarantined", "post_errors",
        "cursor_errors", "cursor_resets", "quarantine_errors", "errors",
        "write_errors", "sink_errors", "dropped", "pending_writes",
        "prune_deferred", "repaired_tails", "error",
    }
    assert required <= set(health)
    assert health["backlog"] == 1 and health["backlog_bytes"] > 0
    assert health["write_errors"] == 2
    assert health["dropped"] == 3 and health["pending_writes"] == 1


def test_outbox_oldest_age_comes_from_head_row_not_fresh_file_mtime():
    directory = tempfile.mkdtemp(prefix="health_oldest_row_")
    now = datetime.now(timezone.utc)
    path = _write_rows(directory, [
        _row(1, ts_utc=(now - timedelta(hours=2)).isoformat()),
        _row(2, ts_utc=now.isoformat()),
    ])
    # A recent append refreshes file mtime but must not rejuvenate the
    # first unacknowledged record.
    os.utime(path, None)
    replayer = de.OutboxReplayer(directory, "http://unused")
    assert replayer._save_cursor({
        "file": os.path.basename(path),
        "pos": 0,
    })
    health = replayer.health()
    assert health["cursor_ok"] is True
    assert 7100 <= health["oldest_unsent_age_s"] <= 7300


def test_outbox_unprovable_head_timestamp_fails_health_closed():
    directory = tempfile.mkdtemp(prefix="health_bad_timestamp_")
    _write_rows(directory, [_row(1)])
    health = de.OutboxReplayer(
        directory, "http://unused").health()
    assert health["cursor_ok"] is False
    assert health["error"] is True


def test_outbox_enumeration_failure_is_not_a_healthy_empty_queue(monkeypatch):
    directory = tempfile.mkdtemp(prefix="health_list_fail_")
    rep = de.OutboxReplayer(directory, "http://unused")

    real_listdir = de.os.listdir

    def broken_listdir(path):
        if os.path.abspath(path) == os.path.abspath(directory):
            raise OSError("simulated directory I/O failure")
        return real_listdir(path)

    monkeypatch.setattr(de.os, "listdir", broken_listdir)
    health = rep.health()
    assert health["cursor_ok"] is False
    assert health["error"] is True
    assert health["scan_errors"] == 1
    assert rep.replay_once() == 0
    assert rep.errors == 1


def test_outbox_unreadable_unacked_file_fails_health_closed(monkeypatch):
    directory = tempfile.mkdtemp(prefix="health_file_fail_")
    path = _write_rows(
        directory,
        [_row(1, ts_utc=datetime.now(timezone.utc).isoformat())])
    rep = de.OutboxReplayer(directory, "http://unused")
    assert rep._save_cursor({"file": os.path.basename(path), "pos": 0})
    real_getsize = de.os.path.getsize

    def broken_getsize(candidate):
        if os.path.abspath(candidate) == os.path.abspath(path):
            raise OSError("simulated unreadable outbox file")
        return real_getsize(candidate)

    monkeypatch.setattr(de.os.path, "getsize", broken_getsize)
    health = rep.health()
    assert health["cursor_ok"] is False
    assert health["error"] is True
    assert health["scan_errors"] == 1


def test_size_retention_preserves_unacked_and_prunes_only_cursor_predecessors():
    directory = tempfile.mkdtemp(prefix="retention_size_")
    for day in ("20260721", "20260722", "20260723"):
        _write_rows(
            directory,
            [_row(int(day[-2:]), ts_utc="2026-07-21T00:00:00+00:00",
                  padding="x" * 4096)],
            name=f"diag-{day}.jsonl")
    sink = de.JsonlSink(
        directory, flush_n=1, today=lambda: "20260723")
    rep = de.OutboxReplayer(directory, "http://unused", sink=sink)
    cap = 1024

    # No cursor and an invalid cursor prove no acknowledgement; all daily
    # files survive even though the cap is exceeded.
    assert sink.prune_to_size(cap)["pruned"] == []
    assert len(rep._outbox_files()) == 3
    with open(rep.cursor_path, "w", encoding="utf-8") as handle:
        json.dump({"file": "diag-20260723.jsonl", "pos": 999999}, handle)
    assert sink.prune_to_size(cap)["pruned"] == []
    assert len(rep._outbox_files()) == 3

    # Cursor at the newest file proves only strict predecessors are resolved.
    assert rep._save_cursor({"file": "diag-20260723.jsonl", "pos": 0})
    result = sink.prune_to_size(cap)
    assert result["pruned"] == [
        "diag-20260721.jsonl",
        "diag-20260722.jsonl",
    ]
    assert rep._outbox_files() == ["diag-20260723.jsonl"]


def test_disabled_writer_builds_no_delivery_leg_and_heartbeat_fails_closed(
        tmp_path, monkeypatch):
    monkeypatch.setenv(de.ENABLE_ENV, "0")
    monkeypatch.setenv(de.SERVER_URL_ENV, "http://unused")
    monkeypatch.setenv(de.DIR_ENV, str(tmp_path))
    writer = de.DiagWriter()

    assert writer.enabled is False
    assert writer.sinks == []
    assert writer.outbox_active() is False
    assert not isinstance(writer.outbox, de.OutboxReplayer)
    assert writer.start() is False
    stats = writer.stats()
    assert stats["diagnostics_disabled"] is True
    assert stats["health_unavailable"] is True
    assert stats["sinks"] == {}
    assert stats["outbox"]["diagnostics_disabled"] is True
    assert stats["outbox"]["health_unavailable"] is True
    assert stats["outbox"]["cursor_ok"] is False
    assert stats["outbox"]["error"] is True
    assert list(tmp_path.iterdir()) == []

    # Exercise the actual controller heartbeat assembly, which reads
    # writer.outbox.health() directly.
    import controller_daemon as cd

    class Link:
        def fw_identity(self):
            return {
                "pcb": "revD", "rid": 1, "uid": "test-uid",
                "build": "test-build", "cfg": "test-cfg", "fw": "1.2.3",
            }

        def parse_health(self):
            return {"parse_errors": 0, "diag_record_drops": 0}

        def fw_version(self):
            return "1.2.3"

    class Config:
        lane = 21
        board_rev = "revD"

    class Board:
        cfg = Config()
        link = Link()
        control_loop_seq = 7

        @staticmethod
        def telemetry_snapshot():
            return {
                "lane_id": 21,
                "controller_boot_id": cd._CONTROLLER_BOOT_ID,
                "control_loop_seq": 7,
                "board_rev": "revD",
                "observed_pcb": "revD",
                "observed_rid": "1",
                "observed_uid": "test-uid",
                "fw_build": "test-build",
                "fw_cfg": "test-cfg",
                "fw_version": "1.2.3",
                "identity_ok": True,
                "identity_reason": None,
                "controller_mode": "live",
                "live_outputs_acknowledged": True,
                "arm_state": True,
                "fsm_state": "ready",
                "manual_rearm_required": False,
                "legacy_identity_mode": False,
                "identity_assurance": "verified",
                "arm_prerequisite_reason": None,
                "safety_taps": {
                    "ne555": True,
                    "wdog_kick": True,
                    "arm_permit": True,
                    "rp2040_ok": True,
                },
                "parse_errors": 0,
                "quarantined_lines": 0,
                "diag_record_drops": 0,
                "pending_diag_records": 0,
                "_link_hb_generation": 1,
                "_link_discontinuity_generation": 0,
            }

        @staticmethod
        def _identity_arm_ok(allow_shadow_bypass=False):
            return True, None

        @staticmethod
        def runtime_diagnostics(identity_verdict=None):
            return {
                "controller_mode": "live",
                "live_outputs_acknowledged": True,
                "arm_state": True,
                "fsm_state": "ready",
                "manual_rearm_required": False,
                "legacy_identity_mode": False,
                "identity_assurance": "verified",
                "arm_prerequisite_reason": None,
                "safety_taps": {
                    "ne555": True,
                    "wdog_kick": True,
                    "arm_permit": True,
                    "rp2040_ok": True,
                },
            }

    platform = cd.PlatformHealth(
        [Board()], writer, dir_path=str(tmp_path))
    platform._hb_url = "http://unused"
    platform._hb_interval = 0
    sent = []
    platform._post_heartbeat = sent.append
    platform._maybe_heartbeat()
    assert len(sent) == 1
    heartbeat_outbox = sent[0]["outbox"]
    assert heartbeat_outbox["diagnostics_disabled"] is True
    assert heartbeat_outbox["health_unavailable"] is True
    assert heartbeat_outbox["cursor_ok"] is False
    assert heartbeat_outbox["error"] is True
    assert sent[0]["controller_mode"] == "live"
    assert sent[0]["identity_assurance"] == "verified"


def test_cycle_shipper_has_no_second_queue_before_durable_writer():
    class DurableWriter:
        def __init__(self):
            self.rows = []

        def outbox_active(self):
            return True

        def emit_cycle(self, row):
            self.rows.append(row)
            return True

    writer = DurableWriter()
    shipper = CycleShipper(writer.emit_cycle, maxsize=1)
    assert shipper.direct_to_durable is True
    assert shipper.start() is True
    assert shipper.offer({"seq": 1}) is True
    assert shipper.offer({"seq": 2}) is True
    shipper.stop()
    assert writer.rows == [{"seq": 1}, {"seq": 2}]
    assert shipper.stats() == {
        "direct_to_durable": True,
        "pending": 0,
        "drops": 0,
        "shipped": 2,
        "errors": 0,
    }


def test_quarantine_loss_latch_survives_restart_and_requires_audited_clear(
        tmp_path):
    _write_rows(str(tmp_path), [_row(41)])

    def reject(_url, payload):
        return _event_ack(
            payload, accepted=0,
            rejected=[{"index": 0, "error": "producer drift"}])

    first = de.OutboxReplayer(str(tmp_path), "http://unused", post=reject)
    assert first.replay_once() == 1
    assert first.health()["quarantined"] == 1
    assert os.path.exists(first.quarantine_state_path)

    restarted = de.OutboxReplayer(
        str(tmp_path), "http://unused",
        post=lambda _u, p: _event_ack(p, duplicates=len(p["events"])))
    assert restarted.health()["quarantined"] == 1

    audit = restarted.clear_quarantine_latch(
        "mechanic-17", "record reconciled against paper score")
    assert audit["quarantined"] == 1
    assert restarted.health()["quarantined"] == 0
    after_clear = de.OutboxReplayer(str(tmp_path), "http://unused")
    assert after_clear.health()["quarantined"] == 0
    assert os.path.getsize(after_clear.quarantine_clear_audit_path) > 0


def test_cycle_quarantine_latch_is_persistent(tmp_path):
    cycle = _row(42, _kind="cycle", final_state="READY")
    _write_rows(str(tmp_path), [cycle])

    def reject_cycle(_url, _payload):
        return {
            "ok": True, "accepted": 0, "duplicates": 0,
            "rejected": [{"index": 0, "error": "bad cycle"}],
            "id": None,
        }

    first = de.OutboxReplayer(
        str(tmp_path), "http://unused", post=reject_cycle)
    assert first.replay_once() == 1
    assert first.health()["cycles_quarantined"] == 1
    restarted = de.OutboxReplayer(str(tmp_path), "http://unused")
    assert restarted.health()["cycles_quarantined"] == 1


def test_quarantine_restart_recovers_evidence_newer_than_state_watermark(
        tmp_path):
    rep = de.OutboxReplayer(str(tmp_path), "http://unused")
    rep.quarantined = 0
    rep.cycles_quarantined = 0
    rep._loss_seq = 4
    rep._cleared_through_loss_seq = 4
    assert rep._persist_quarantine_state()

    # Simulate power loss after evidence fsync but before the atomic state
    # replace. The valid old state says zero; the newer loss_seq must win.
    evidence = {
        "loss_seq": 5,
        "error": "server rejected",
        "row": _row(55),
    }
    with open(rep.quarantine_path, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(evidence) + "\n")
        handle.flush()
        os.fsync(handle.fileno())

    restarted = de.OutboxReplayer(str(tmp_path), "http://unused")
    health = restarted.health()
    assert health["quarantined"] == 1
    assert restarted._loss_seq == 5
