from revagent.reviewer_packs import available_reviewer_packs, load_reviewer_pack


def test_computational_mathematics_reviewer_packs_define_safety_guidance() -> None:
    assert {"numerical-pde", "optimization-linear-algebra", "stability-convergence", "stochastic-uq", "scientific-software-hpc", "computational-physics", "statistics-ml", "engineering-computation"} <= set(available_reviewer_packs())
    pack = load_reviewer_pack("numerical-pde")
    assert pack["claim_types"] and pack["assumptions"] and pack["minimum_evidence"] and pack["stress_tests"]
