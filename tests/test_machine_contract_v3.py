#!/usr/bin/env python3
"""Focused invariants for the Phase-8 scoring/command protocol-v3 contract."""

import importlib.util
import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = REPO_ROOT / "server" / "machine_contract.json"
LOADER_PATH = REPO_ROOT / "server" / "machine_contract.py"


def _contract():
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


def _loader():
    spec = importlib.util.spec_from_file_location(
        "machine_contract_v3_test", LOADER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_protocol_v3_scoring_frames_and_durable_ack_contract():
    contract = _contract()
    ws = contract["endpoints"]["scoring_websocket"]
    vocab = contract["vocab"]

    assert contract["contract_version"] == 3
    assert contract["scoring_protocol"]["version"] == 3
    assert ws["protocol_version"] == 3
    assert "token" in ws["hello_required_fields"]
    assert "scoring_epochs" in ws["heartbeat_ack_required_fields"]
    auth_posture = contract["auth"]["posture"]
    assert "LANE_NODE_TOKEN is mandatory for every HTTP mutation" in (
        auth_posture)
    assert "WSL_SCORING_NODE_TOKEN" in auth_posture
    assert "WSL_SCORING_NODE_TOKENS" in auth_posture
    assert "WebSocket HELLO authentication" in auth_posture
    assert (
        "LANE_NODE_TOKEN is mandatory for every POST and WebSocket HELLO"
        not in auth_posture)

    scoring_fields = {
        "scoring_event_queue_depth",
        "scoring_event_queue_capacity",
        "scoring_event_oldest_age_s",
        "scoring_capture_jobs",
        "scoring_capture_oldest_age_s",
        "scoring_clock_observed",
        "scoring_clock_anomaly_latched",
        "scoring_clock_high_water_epoch",
        "scoring_clock_observed_epoch",
        "scoring_event_durable",
        "scoring_event_error",
        "scoring_event_overdue",
        "scoring_event_drops",
        "scoring_event_expired",
        "scoring_event_max_age_s",
    }
    assert set(ws["scoring_transport_outbox_required_fields"]) == scoring_fields
    assert scoring_fields <= set(ws["outbox_required_fields"])

    event_frames = ws["scoring_event_frames"]
    for field in ("event_id", "event_created_at", "scoring_epoch"):
        assert field in event_frames["ball_event_required_fields"]
        assert field in event_frames["foul_event_required_fields"]
    assert set(event_frames["ball_event_optional_fields"]) == {
        "awaiting_manual", "capture_interrupted"}
    assert "reserves the physical camera edge's global FIFO position" in (
        event_frames["receipt_semantics"])
    assert "capture_interrupted_manual_only" in (
        event_frames["receipt_semantics"])
    dispositions = set(ws["scoring_event_ack"]["dispositions"])
    assert dispositions == set(vocab["scoring_event_dispositions"])
    assert "overdue_quarantined" in dispositions
    assert set(vocab["scoring_event_types"]) == {"ball_event", "foul_event"}


def test_command_receipt_and_non_actuating_epoch_sync_contract():
    contract = _contract()
    ws = contract["endpoints"]["scoring_websocket"]
    commands = ws["command_frames"]
    ack = ws["command_ack"]
    vocab = contract["vocab"]

    assert commands["types"] == vocab["command_types"]
    assert commands["actuating_types"] == vocab["actuating_command_types"]
    assert commands["non_actuating_types"] == ["scoring_epoch_sync"]
    assert commands["scoring_epoch_sync_additional_required_fields"] == [
        "scoring_epoch", "session_generation"]
    assert {"command_id", "issued_at"} <= set(
        commands["common_required_fields"])
    assert ack["statuses"] == vocab["command_ack_statuses"]
    assert {"duplicate", "refused", "ambiguous", "failed"} <= set(
        ack["statuses"])
    assert "payload" in commands["retry_semantics"]
    assert "permanent safety tombstones" in commands["retry_semantics"]
    assert "never pulse" in commands["scoring_epoch_sync_semantics"]
    assert "freshly renewed" in commands["scoring_epoch_sync_semantics"]
    assert "started receipt is safely reclaimable" in (
        commands["scoring_epoch_sync_semantics"])


def test_generation_transfer_and_manual_reconciliation_contract():
    contract = _contract()
    endpoints = contract["endpoints"]
    assert "WSL_SCORING_NODE_TOPOLOGY" in (
        contract["scoring_protocol"]["node_topology"])
    assert "no newest-claimant routing" in (
        contract["scoring_protocol"]["node_topology"])

    opened = endpoints["lane_open_post"]
    assert set(opened["body_required_fields"]) == {
        "bowlers", "send_open_command", "session_generation"}
    assert opened["body_optional_fields"] == []
    assert "request_fingerprint" in opened
    assert {"request_fingerprint", "bowlers"} <= set(
        opened["response_ok_fields"])
    assert "reconciliation_required" in opened["response_ok_fields"]
    assert "desired-state repair path" in opened["semantics"]
    assert "can never be replayed" in opened["semantics"]
    assert "pending_manual_scores" in opened["semantics"]

    paired = endpoints["pair_open_league_post"]
    assert set(paired["body_required_fields"]) == {
        "team1_bowlers", "team2_bowlers", "team1_name", "team2_name",
        "send_open_command", "session_generations"}
    assert paired["body_optional_fields"] == []
    assert "request_fingerprint" in paired
    assert {"scoring_epoch", "request_fingerprint", "team1_name",
            "team2_name", "team1_bowlers", "team2_bowlers"} <= set(
                paired["response_ok_fields"])
    assert "send_open_command=false" in paired["semantics"]
    assert "cannot later escalate" in paired["semantics"]

    transfer = endpoints["lane_transfer_post"]
    assert transfer["path"] == "/api/lane/transfer"
    assert set(transfer["body_required_fields"]) == {
        "from_lane", "to_lane", "paired_from", "paired_to",
        "session_generations", "send_hardware_commands",
    }
    assert {"scoring_epoch", "request_fingerprint", "sent_close_commands",
            "sent_open_commands", "reconciliation_required"} <= set(
                transfer["response_ok_fields"])
    assert "preserves every bowler, frame, score, and scoring_epoch" in (
        transfer["semantics"])
    assert "renewable non-actuating" in transfer["semantics"]

    manual = endpoints["lane_manual_score_post"]
    assert manual["body_required_fields"] == ["event_id", "pin_mask"]
    assert manual["body_optional_fields"] == ["foul"]
    assert "server computes" in manual["request_fingerprint"]
    assert "one transaction" in manual["semantics"]
    assert "capture_interrupted_manual_only" in manual["semantics"]

    trigger = endpoints["lane_trigger_ball_post"]
    assert trigger["required_headers"] == [
        "X-Operation-Key", "X-Operation-Issued-At"]
    assert {"operation_key", "request_fingerprint", "session_generation",
            "scoring_epoch", "replayed"} <= set(
                trigger["response_ok_fields"])
    assert "one SQLite transaction" in trigger["semantics"]

    scoring = endpoints["lane_scoring_get"]
    assert scoring["generation_states"] == [
        "active", "retired", "never_opened"]
    assert {"session_generation", "scoring_epoch",
            "pending_manual_scores"} <= set(
                scoring["closed_response_required_fields"])
    assert "scoring_generation_state_inconsistent" in scoring["semantics"]

    manual_resolution = endpoints["manual_score_resolution_post"]
    assert manual_resolution["body_required_fields"] == [
        "event_id", "actor_id", "disposition", "note"]
    assert manual_resolution["body_optional_fields"] == []
    assert set(manual_resolution["dispositions"]) == {
        "false_trigger_discarded", "session_abandoned"}
    assert "hardware command" in manual_resolution["semantics"]

    diagnostics = endpoints["lane_diagnostics_get"]
    assert {"open_incidents", "resolution_audit"} <= set(
        diagnostics["response_top_fields"])
    assert "cannot make health green" in diagnostics["semantics"]

    backup_fence = endpoints["backup_fence"]
    assert backup_fence["acquire"]["path"] == (
        "/api/system/backup-fence/acquire")
    assert set(backup_fence["acquire"]["body_required_fields"]) == {
        "fence_id", "lease_seconds", "expected_lanes"}
    assert backup_fence["verify"]["body_required_fields"] == [
        "fence_id", "expected_lanes"]
    assert backup_fence["release"]["body_required_fields"] == ["fence_id"]
    assert "LANE_NODE_TOKEN" in backup_fence["authentication"]
    assert "safety_ledgers" in backup_fence["response_ok_fields"]
    assert set(backup_fence["durable_safety_tables"]) == {
        "diagnostic_incident_outbox", "background_command_deliveries"}
    assert backup_fence["server_acquire_timeout_seconds"] == 8
    assert set(backup_fence["store_identity_fields"]) == {
        "canonical_path", "device", "inode", "size_bytes", "mtime_ns",
        "schema_version", "user_version", "page_count", "freelist_count",
        "logical_size_bytes", "content_sha256", "schema_sha256"}
    assert "machine_diag database lock" in backup_fence["semantics"]
    assert "Verify must succeed" in backup_fence["semantics"]

    resolve = endpoints["event_resolve_post"]
    allowed = {
        frozenset(shape["required_fields"])
        for shape in resolve["body_allowed_shapes"]
    }
    assert allowed == {
        frozenset({"resolved_by", "recovery_event_id"}),
        frozenset({"resolved_by", "override"}),
    }
    override = next(
        shape for shape in resolve["body_allowed_shapes"]
        if "override" in shape["required_fields"])
    assert override["override_required_fields"] == ["actor_id", "reason"]
    assert override["override_exact"] is True
    assert override["override_actor_must_match"] == "resolved_by"
    assert resolve["response_ok_fields"] == ["ok", "event", "resolution"]
    assert "remains DEGRADED" in resolve["semantics"]

    persistence = endpoints["health_get_identity"]
    assert "strict format-v2 JSON" in persistence["note"]
    assert "pickle is never deserialized" in persistence["note"]
    assert "node_topology" in persistence["identity_fields"]
    assert "scoring_node_topology" in (
        endpoints["machine_health_get"]["response_top_fields"])
    assert "diagnostic_delivery" in (
        endpoints["machine_health_get"]["response_top_fields"])


def test_frozen_fallback_matches_live_protocol_v3_vocabulary(tmp_path):
    contract = _contract()
    live = contract["vocab"]
    loader = _loader()
    fallback = loader.load_vocab(
        tmp_path / "missing-contract.json", allow_fallback=True)

    assert loader.FALLBACK_PROTOCOL_VERSION == 3
    for key in (
            "scoring_event_types", "scoring_event_dispositions",
            "command_types", "actuating_command_types",
            "command_ack_statuses", "manual_reconciliation_conditions"):
        assert tuple(fallback[key]) == tuple(live[key])
    assert set(fallback["event_types"]) == set(live["event_types"])
    assert {"command_transport", "scoring_event_transport"} <= set(
        fallback["event_types"])
