from app.services.workflow import run_case_pipeline, verify_trace_chain


def test_trace_hash_chain_is_internally_consistent():
    artifacts = run_case_pipeline()
    assert verify_trace_chain(artifacts.case["case_id"], artifacts.trace_events)


def test_trace_hash_chain_detects_tampering():
    artifacts = run_case_pipeline()
    tampered = list(artifacts.trace_events)
    tampered[3].event_type = "TAMPERED"
    assert not verify_trace_chain(artifacts.case["case_id"], tampered)


def test_trace_hash_chain_detects_reordering():
    artifacts = run_case_pipeline()
    tampered = list(artifacts.trace_events)
    tampered[1].sequence, tampered[2].sequence = tampered[2].sequence, tampered[1].sequence
    assert not verify_trace_chain(artifacts.case["case_id"], tampered)


def test_state_transitions_are_recorded_and_valid():
    artifacts = run_case_pipeline()
    transitions = [e for e in artifacts.trace_events if e.event_type == "STATE_TRANSITION"]
    assert len(transitions) >= 5
    assert transitions[-1].argument_hash is not None


def test_replay_produces_byte_identical_hash_chain():
    # The chain hashes fold in stage/event_type/tool/evidence/arguments only —
    # never timestamps — so two independent runs of the same fixture must
    # produce the exact same final chain hash. This is the property that
    # makes a stored trace independently reproducible, not just internally
    # self-consistent.
    first = run_case_pipeline()
    second = run_case_pipeline()
    assert [e.state_after_hash for e in first.trace_events] == [e.state_after_hash for e in second.trace_events]
