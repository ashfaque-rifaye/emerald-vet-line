"""What must still happen when a model or a connection fails."""

from emerald import ledger, pipeline


def types(case_id):
    return [e["type"] for e in ledger.entries(case_id)]


def test_a_model_failure_still_calls_the_vet(monkeypatch):
    def broken(*args, **kwargs):
        raise ConnectionError("the model is unreachable")

    monkeypatch.setattr(pipeline, "_gather_evidence", broken)
    outcome = pipeline.handle_case("F001", ["skin_nodules", "fever"], weight_kg=300)
    assert outcome.status == "done"
    assert "vet_called" in types(outcome.case_id) and "evidence_unavailable" in types(outcome.case_id)


def test_a_model_failure_cannot_stop_red_flag_steps(monkeypatch):
    def broken(*args, **kwargs):
        raise ConnectionError("the model is unreachable")

    monkeypatch.setattr(pipeline, "_gather_evidence", broken)
    outcome = pipeline.handle_case("F001", ["sudden_death", "bleeding_from_body_openings"])
    recorded = types(outcome.case_id)
    assert "farmer_told" in recorded and "doctor_called" in recorded and "vet_called" in recorded


def test_no_verified_evidence_means_no_action_agent(monkeypatch):
    from emerald import proof_graph

    monkeypatch.setattr(pipeline, "_gather_evidence", lambda *a: proof_graph.ProofRun("x", {}))
    outcome = pipeline.handle_case("F001", ["skin_nodules"], weight_kg=300)
    recorded = types(outcome.case_id)
    assert "signoff_requested" not in recorded and "vet_called" in recorded


def test_a_tool_server_failure_leaves_the_case_with_the_vet(monkeypatch):
    from emerald import proof, proof_graph

    run = proof_graph.ProofRun("x", {})
    run.verified = [proof.ClaimCheck(claim=proof.Claim(claim="c", passage_id="p", quote="q"), ok=True, reason="r")]
    monkeypatch.setattr(pipeline, "_gather_evidence", lambda *a: run)

    def broken(*servers):
        raise RuntimeError("a tool server would not start")

    monkeypatch.setattr(pipeline, "connected", broken)
    outcome = pipeline.handle_case("F001", ["skin_nodules"], weight_kg=300)
    recorded = types(outcome.case_id)
    assert outcome.status == "done" and "vet_called" in recorded and "action_agent_failed" in recorded


def test_farmer_always_hears_safe_words_even_with_no_evidence(monkeypatch):
    from emerald import proof_graph

    monkeypatch.setattr(pipeline, "_gather_evidence", lambda *a: proof_graph.ProofRun("x", {}))
    outcome = pipeline.handle_case("F001", ["skin_nodules"], weight_kg=300)
    assert "farmer_told" in types(outcome.case_id)


def test_resume_with_nothing_saved_does_nothing():
    assert pipeline.resume("C-unknown").status == "done"


def test_resume_waits_for_a_run_that_is_still_saving_its_pause():
    """A fast vet: the signature lands while the agent's run still holds the case."""
    import threading
    import time

    order = []
    lock = pipeline._case_lock("C-race")
    lock.acquire()

    def resumer():
        pipeline.resume("C-race")
        order.append("resume")

    worker = threading.Thread(target=resumer)
    worker.start()
    time.sleep(0.2)
    order.append("run finished")
    lock.release()
    worker.join(timeout=5)
    assert order == ["run finished", "resume"]
