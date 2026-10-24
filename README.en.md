# production-readiness-agentes

*English translation of [`README.md`](README.md), which is the original. The project's
documentation, corpus and results are in Spanish.*

A framework for deciding whether a conversational agent built on a large language model is
ready for production, and a complete case study applying it: a pre-sales agent for a fictional
consumer-electronics store.

The question this framework tries to answer is not whether the agent works well. It is
**whether it works well enough, and consistently enough, to put it in front of customers**.
Those are two different things, and the second is rarely measured. The undefended agent gets
98.5 % of attempts right, and yet **only 39 of the 42 cases are resolved all eight times in a
row**. That difference is what decides whether anyone ships it.

The framework measures three dimensions and consolidates them into a conjunctive verdict.
Robustness, security, compliance and, from operation, **only the latency overhead** measured
with the four configurations interleaved are binding. Absolute TTFT is measured and reported
but does not decide: its value reflects provider load as much as the system.

| Dimension | Question | Metric |
|---|---|---|
| **Robustness** | Does it resolve the task consistently, despite non-determinism? | pass^k, unbiased estimator with a bootstrap interval over cases |
| **Security** | Does it resist prompt injection, direct and indirect? | attack success rate, by vector and by objective, plus utility on benign cases |
| **Compliance** | Does it satisfy checkable regulatory obligations? | executable checklist derived from Chile's Law 21.719 and the SERNAC 2022 circular |

## Effectiveness is not efficiency

The result hardest to see from a single run is that **injection defenses cost little
effectiveness and a great deal of time**. All four configurations resolve the task about
equally well, and one of them takes nearly seven times longer to start answering.

The four configurations compared:

- **`none`**: no defense. This is the baseline, and for it to be a real baseline its prompt
  does not pre-emptively deny any of the corpus's attack objectives.
- **`prompt_only`**: the defense lives only in the system prompt: clauses that deny each attack
  objective, plus a paragraph telling the model to treat retrieved content as untrusted data.
- **`dual_llm`**: untrusted content (reviews, product descriptions) goes through a quarantined
  model that returns a structured summary; the privileged model never sees the raw text. Its
  system prompt also carries **the same warning paragraph** as `prompt_only`, but not the
  clauses: what sets it apart from `prompt_only` is the quarantine and the missing clauses, not
  the warning.
- **`cte`**: a simplified Code-Then-Execute, inspired by CaMeL. A planner writes a plan and an
  interpreter runs it, so untrusted text cannot alter control flow. It is not a CaMeL replica.
  The planner has its own system prompt, with neither the warning paragraph nor the clauses.

The definitions are in [`src/prf/agent/configuraciones.py`](src/prf/agent/configuraciones.py).

**Models and temperatures**, per [`configs/models.yaml`](configs/models.yaml): the agent
(`claude-sonnet-4-6`) runs at temperature **1.0**, on purpose, because pass^k measures the
effect of that non-determinism; the user simulator and the corpus writer
(`claude-haiku-4-5-20251001`) at **0.7**; and the Code-Then-Execute planner and the judge
(Sonnet) and the quarantined model (Haiku) at **0**. Extended thinking is off in every role.

## Results

Measured with `claude-sonnet-4-6` as the agent, over the **test partition** of the frozen
synthetic corpus: 179 of its 256 cases. Compliance is the exception and is measured over its
full 26 cases. Every figure comes from a file in [`results/`](results/), and
[`docs/CIFRAS_INFORME.md`](docs/CIFRAS_INFORME.md) says which one.

| | `none` | `prompt_only` | `dual_llm` | `cte` |
|---|---:|---:|---:|---:|
| **Verdict** | GO | GO | GO | **NO-GO** |
| pass^1 | 0.985 | 0.979 | 0.973 | 0.970 |
| pass^8 | 0.929 | 0.905 | 0.952 | 0.952 |
| Attack success rate, overall | 0.004 | 0.000 | 0.004 | 0.011 |
| … direct vector | 0.000 | 0.000 | 0.012 | 0.036 |
| … indirect vector | 0.005 | 0.000 | 0.000 | 0.000 |
| Utility on benign cases | 1.000 | 0.988 | 0.988 | 0.988 |
| TTFT p95 | 2.20 s | 2.42 s | 2.85 s | **15.31 s** |
| Latency overhead vs `none` | 1.00× | 1.10× | 1.29× | **6.95×** |
| Critical compliance items | 23/23 | 23/23 | 23/23 | **22/23** |

Three readings the table supports, and that should not be stretched further:

**No defense degrades robustness in an interpretable way.** The pass^8 differences amount to
one or two cases out of 42 and the intervals overlap across all six pairs. What the experiment
supports is not that one configuration beats another, but that none falls below the baseline
beyond the margin the policy sets, **0.05 on pass^1**.

**The cost of the defenses is waiting time, not accuracy or total work.** `dual_llm` costs
29 % more TTFT and `cte` nearly seven times. What should be read alongside it: `cte`'s
**end-to-end** latency is the lowest of the four, 0.79× the baseline at p95. It is not doing
more work; it **shows nothing while it plans and executes**: the customer waits 11.86 seconds
in front of an empty screen at the median, and 15.31 at the 95th percentile.

The verdict does capture this, through the overhead: 6.95× against a 2.0× ceiling, one of the
two rules that leave `cte` at NO-GO. What is not binding is absolute TTFT, whose 1.5 s target
**none of the four configurations meets**. This is declared in
[`docs/LIMITACIONES.md`](docs/LIMITACIONES.md).

**The policy is not a property of the system but of the system-model pair.** Three of the
configurations were also measured with `claude-haiku-4-5`, over the same corpus and with the
same criterion. The attack success rate goes from 0.005 to **0.129** undefended, stays at
**0.081** with Dual LLM and rises to **0.186** with Code-Then-Execute, which reaches **0.464 on
the direct vector**. **None of the three meets security.** Changing models forces a
re-measurement.

### Why `cte` fails

The verdict cites the rule and its value. `cte` violates `cumplimiento.items_criticos`, at 22
of 23 critical items, and `operacion.sobrecosto_latencia`, at 6.95× against a 2.0× limit.

The missing critical item does not fail: it comes out **not evaluable**. It is price
truthfulness, and the reason is in the case that exercises it, `CUM-003`, where the customer
asks for "the exact price of that product" without naming it. `cte`'s single-pass pattern
cannot ask back, so the answer cites no catalog product and there is no price to check. A
critical item that cannot be evaluated is not counted as passing.

Separately, and as a diagnostic that **does not enter the verdict**, the results-truthfulness
item applied to the 1,344 robustness runs flags 8, all of them `cte` and all from the same
case, `ROB-BUS-007`: the agent claims not to carry products its own search had just returned.
It is not binding because it was measured over runs made for another dimension, with an item
written after seeing them.

### External annotation did not confirm the author's

A person outside the project reviewed the 64 runs of the agreement sample blind, without seeing
the configuration, the case type or anyone's verdict. The reading rule was fixed **before**
their answers arrived, in
[`docs/E6_REGLA_DE_INTERPRETACION.md`](docs/E6_REGLA_DE_INTERPRETACION.md), and it produced two
uncomfortable results:

- **The author's annotation is not confirmed**: Cohen's kappa of −0.20 against the blind
  annotation, below the 0.60 threshold fixed in advance. It is reported as a single annotator
  without external validation.
- **The permissive one is the automated judge, not the person.** The blind annotation agrees
  **more** with the state evaluator (kappa 0.43) than with the judge (kappa −0.20), and where
  the person saw that some option failed what was asked they said the answer served them in
  only 4 of 17 cases: on constraints they side with the evaluator.
- **`pass^k` is not presented as a lower bound on perceived utility.** Not because the human
  criterion is stricter, which it is not: the person approved 48 of 64 and the evaluator 40.
  It is that **the ordering is not clean in either direction**. The evaluator rejects 12 runs
  the person approved, among them three where it fails on how it reads state and the eight
  false denials by `cte`, and approves 4 that they rejected.

## Installation

Requires Python 3.11 or 3.12.

```bash
git clone https://github.com/jplazcano87/production-readiness-agentes.git
cd production-readiness-agentes
uv sync                    # or: pip install -e ".[dev]"
```

To install the environment the no-API steps run under, which is the one used for the October
runs (what the lock file can and cannot claim is in
[`docs/REPRODUCIBILIDAD.md`](docs/REPRODUCIBILIDAD.md)):

```bash
uv pip install -r requirements-lock.txt
```

## Verifying without calling the API

This is the first thing worth running, and it needs no key and no network.

```bash
pytest -q                                      # the whole suite, no network
python scripts/verificar_equivalencia.py       # fingerprints of the frozen artifacts
python scripts/verificar_equivalencia.py --completo   # also regenerates and compares them
```

The full mode copies the tree to a temporary directory, creates its own virtual environment
there with the package installed non-editable, regenerates twelve derived artifacts and
compares them with the published ones: Markdown and CSV byte for byte, PNG pixel by pixel, JSON
field by field. It also checks that the repository did not change in the meantime. Details in
[`docs/REPRODUCIBILIDAD.md`](docs/REPRODUCIBILIDAD.md).

## Running with the API

The key goes in a `.env` file, which is never versioned. There is an `.env.example` with the
variable names and no values.

```bash
cp .env.example .env        # then write your ANTHROPIC_API_KEY there
```

**Every script that calls the API accepts `--dry-run`, which prints tokens and estimated cost
in dollars without calling anything.** Always run it first.

```bash
python scripts/run_e1.py --dry-run     # what it would cost
python scripts/run_e1.py --piloto 2    # two cases per configuration, to validate
python scripts/run_e1.py               # the full run
```

Each result records in its metadata the tokens consumed and the real cost of that run, so the
file states what it cost to produce. The pre-flight gate (`scripts/prevuelo.py`) checks the harness
before spending on a long run: first the static checks, without calling the API; then the
dynamic ones, on a small sample of the four configurations; and finally, that the real cost
stays within 20 % of the estimate.

## Layout

```
configs/      thresholds, models, deployment and the record of what is frozen
data/
  corpus/     five corpus versions, each with its manifest and hash
  splits/     development and test partitions
  templates/  attack templates, separated between development and test
  annotation/ samples and answers from the agreement annotation
docs/         report figures, provenance, reproducibility, limitations,
              defect log, datasheet and the two pre-registrations
figures/      the five report figures
results/      the canonical results and the transcripts of the runs behind every
              published measurement, with the exceptions documented in
              docs/PROCEDENCIA.md
scripts/      the six experiments, the verifier and the no-cost audits
src/prf/      env (sandbox and evaluator), agent (defense configurations),
              eval (metrics), compliance (checklist), verdict, infra
tables/       the report tables
tests/        the suite, which runs without network
```

**What must not be touched** is listed in [`AGENTS.md`](AGENTS.md): corpus, splits, thresholds,
results, transcripts and prompt texts. Changing them does not fix a result, it invalidates it.
`docs/MANIFIESTO_ARTEFACTOS.json` holds the SHA-256 of each one and the verifier checks them.

## Project status

A research artifact from a graduate thesis, maintained part time. The measurements are closed
and the artifacts frozen; what is welcome are replications, new defense configurations, new
attack families, adaptations to other models and providers, and checklist items for other
jurisdictions. See [`CONTRIBUTING.md`](CONTRIBUTING.md).

## What this framework cannot claim

The corpus is synthetic, there is a single model from a single provider, the attacks are static
and single-turn, and the verdict judges the agent and not its deployment. The full list, with
what each one prevents you from claiming, is in
[`docs/LIMITACIONES.md`](docs/LIMITACIONES.md). The 32 defects the framework found in itself
and in the system it evaluates, with what each one changed, are in
[`docs/REGISTRO_DE_DEFECTOS.md`](docs/REGISTRO_DE_DEFECTOS.md).

## Responsible use

The corpus includes **prompt-injection attack templates**, published for defensive evaluation,
as AgentDojo and InjecAgent do. They are generic payloads against a fictional pre-sales agent:
they exploit no vulnerability in any specific product or provider. The development and test
partitions use different templates, and no string is repeated between them, which is what
supports the claim that what was measured on test was not tuned during calibration.

## How to cite

The citation lives in [`CITATION.cff`](CITATION.cff), which is where GitHub reads it from. The
thesis is in Spanish, so its title is given as it is, with a translation in brackets:

> Lazcano Candia, J. P. (2026). *Marco de Production Readiness para Agentes Autónomos de
> Compra en Retail: Integración de Evals, Guardrails y Compliance Normativo para Ecommerce*
> [A production-readiness framework for autonomous retail shopping agents: evals, guardrails
> and regulatory compliance for ecommerce]. Graduation report, Master in Artificial
> Intelligence, Pontificia Universidad Católica de Chile.

The software is archived on Zenodo and has a DOI. To cite **any version**, use the concept DOI:
[10.5281/zenodo.23403716](https://doi.org/10.5281/zenodo.23403716). To cite a specific version, use the DOI of that version: 1.0.0,
[10.5281/zenodo.23403717](https://doi.org/10.5281/zenodo.23403717); 1.1.0,
[10.5281/zenodo.23627444](https://doi.org/10.5281/zenodo.23627444). The latest version is 1.1.1:
[10.5281/zenodo.23628316](https://doi.org/10.5281/zenodo.23628316).

## License

MIT. See [`LICENSE`](LICENSE). It applies to the code, the corpus and the results.
