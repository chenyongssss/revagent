from pathlib import Path


def main() -> None:
    out = Path("results")
    out.mkdir(exist_ok=True)
    (out / "demo_metrics.csv").write_text("seed,error,runtime\n1,0.10,1.0\n", encoding="utf-8")


if __name__ == "__main__":
    main()
