# DeepEval Faithfulness Evaluation Suite

Week 7 evaluation module providing mathematical proof that agent answers remain strictly faithful to retrieved raw MCP JSON records.

---

## 1. Prerequisites & Installation

Install the evaluation dependencies (including DeepEval):

```bash
cd backend
pip install -e .[eval]
```

Ensure your `OPENAI_API_KEY` is configured in your environment or `.env` file:

```bash
export OPENAI_API_KEY="sk-..."
export DEEPEVAL_JUDGE_MODEL="gpt-4o-mini"  # optional, defaults to gpt-4o-mini
```

---

## 2. Running the Evaluation

Execute the evaluation runner from the `backend/` directory:

```bash
python -m evals.run_eval
```

Options:
- `--dataset <path>`: Custom path to a dataset JSON (default: `backend/evals/dataset.json`).
- `--results <path>`: Custom output path for results (default: `backend/evals/results.json`).
- `--model <name>`: LLM judge model (default: `gpt-4o-mini`).
- `--threshold <float>`: Minimum faithfulness score per case (default: `0.8`).

---

## 3. Dataset Design & Ground Truth

The dataset ([`dataset.json`](./dataset.json)) contains 18 carefully crafted evaluation queries across 8 distinct categories, grounded directly against the seeded database (`backend/app/db_setup.py`):

| Category | Cases | Description & Verification Rules |
|---|---|---|
| `single_lookup` | 3 | Specific product pricing (e.g. Starter \$100, Enterprise \$5000, Premium Support \$250). |
| `comparison` | 2 | Cross-tier catalog comparisons requiring retrieval of all product options. |
| `listing` | 2 | Broad inventory enumeration queries. |
| `aggregation_ish` | 2 | Minimum / maximum pricing queries (cheapest / most expensive). |
| `no_match` | 2 | Queries targeting non-existent packages (Platinum, Titanium); expects empty retrieval and zero fabricated citations. |
| `ambiguous` | 2 | Unspecified pricing queries ("How much does it cost?"); triggers full catalog retrieval. |
| `adversarial` | 2 | SQL injection attempts (`'; DROP TABLE products;--`) and prompt injection instructions; tests query safety. |
| `general` | 3 | Pure conversational questions bypassing SQLite retrieval (`evidence is None`). |

---

## 4. Verification Criteria & CI Gating

A run is considered successful and exits with code `0` only if all criteria are satisfied:

1. **Mean Faithfulness Score $\ge 0.80$**: Calculated by DeepEval's `FaithfulnessMetric` using LLM-as-a-judge against the exact raw MCP JSON retrieval context.
2. **Zero Fabricated Citations**: Every `[Product-N]` tag in the output must strictly map to a valid `id` or row present in `evidence`.
3. **Deterministic Retrieval Guarantees**:
   - `general` queries must have `evidence is None` and cite no products.
   - `no_match` queries must have `evidence == []` and cite no products.
   - `expect_retrieval: true` cases must retrieve all expected product IDs.
