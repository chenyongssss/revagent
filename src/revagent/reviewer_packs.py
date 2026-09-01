"""Versioned, local-only computational-mathematics reviewer-pack guidance."""

from __future__ import annotations

PACK_VERSION = 1
_PACKS = {
    "numerical-pde": ("Numerical PDE / FEM / FDM", ["well-posedness", "consistency", "stability", "convergence"], ["boundary conditions", "regularity", "mesh assumptions"], ["mesh refinement and manufactured-solution evidence"], ["missing norm or regime", "unsupported rate claim"], ["coarse/fine mesh and parameter sweep"]),
    "optimization-linear-algebra": ("Optimization, iterative methods, and linear algebra", ["complexity", "convergence", "conditioning"], ["convexity", "preconditioner assumptions", "stopping rule"], ["residual histories and baselines"], ["incomplete stopping criterion", "unfair baseline"], ["ill-conditioned and restart sensitivity"]),
    "stability-convergence": ("ODE/PDE stability and convergence", ["stability", "convergence", "error bound"], ["step-size", "regularity", "norm"], ["parameter/rate tables"], ["missing side condition", "empirical rate stated as proof"], ["boundary and asymptotic regimes"]),
    "stochastic-uq": ("Stochastic numerical methods and UQ", ["estimator", "uncertainty", "sampling error"], ["distribution", "independence", "seed policy"], ["replicates and confidence intervals"], ["single-seed conclusion", "missing uncertainty"], ["seed and distribution shift"]),
    "scientific-software-hpc": ("Scientific software / HPC", ["reproducibility", "scaling", "implementation"], ["hardware", "compiler", "parallel configuration"], ["environment and scaling logs"], ["unreproducible benchmark", "resource claim without setup"], ["strong/weak scaling and repeat runs"]),
    "computational-physics": ("Computational physics", ["model validation", "conservation", "physical interpretation"], ["constitutive model", "units", "initial/boundary conditions"], ["validation benchmark and conservation diagnostics"], ["unvalidated model regime", "unit inconsistency"], ["limiting-case and conservation tests"]),
    "statistics-ml": ("Statistics and machine learning", ["generalization", "calibration", "comparison"], ["data split", "metric", "randomness"], ["ablations and uncertainty"], ["leakage", "unreported variance"], ["split/seed and distribution-shift tests"]),
    "engineering-computation": ("Engineering computation", ["verification", "validation", "robustness"], ["model scope", "material parameters", "loading"], ["benchmark and sensitivity evidence"], ["unjustified extrapolation", "missing validation case"], ["parameter and boundary-condition sensitivity"]),
}


def available_reviewer_packs() -> list[str]:
    return sorted(_PACKS)


def load_reviewer_pack(name: str) -> dict[str, object]:
    if name not in _PACKS:
        raise ValueError(f"unknown reviewer pack {name!r}; choose one of: {', '.join(available_reviewer_packs())}")
    title, claims, assumptions, evidence, objections, stress_tests = _PACKS[name]
    return {"version": PACK_VERSION, "key": name, "title": title, "claim_types": claims, "assumptions": assumptions, "minimum_evidence": evidence, "recurrent_objections": objections, "stress_tests": stress_tests, "journal_mapping": "Apply only alongside a valid local journal rulepack; this pack does not establish journal policy."}
