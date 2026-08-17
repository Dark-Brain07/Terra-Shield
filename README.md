# Terra Shield Permanence Oracle

A permissionless annual oracle that checks public Verra notices and British Columbia wildfire records, then exposes a conservative, consensus-bound permanence status to downstream contracts.


## Scope

This repository contains one standalone GenLayer Intelligent Contract. The MVP supports Verra VCS forest projects whose monitored bounding box is in British Columbia. It does not estimate carbon loss, certify a project, move value, mint credits, or provide a frontend.

### Why GenLayer

The registry evidence is natural-language content. A leader and validators must independently fetch the same official sources, classify the same closed registry event, and agree on the complete consequential tuple before state changes. A conventional backend would remain a single trusted interpreter.

When not to use GenLayer: if an integration only needs to mirror a stable structured registry field without interpretation, a deterministic indexer is simpler.

## Fixed evidence sources

The contract constructs all URLs. Callers cannot supply a host or full URL.

1. Public Verra Registry project detail:

   `https://registry.verra.org/verra/public/program/VCS/projects/<validated-project-id>`

   Registration succeeds only after leader and validators independently render this public record as text with a fixed 10-second post-load wait and agree that it contains the exact submitted VCS ID and project name and lists `Country Canada` and `State/Province BC`. A live browser preflight found only the application shell after five seconds and the complete 2,434-character identity text after ten seconds; this is timing evidence, not a Studionet transaction or GenVM execution claim.

2. Verra Views WordPress API:

   `https://verra.org/wp-json/wp/v2/verra-views?slug=<validated-slug>&_fields=id,date,slug,link,title,content`

3. British Columbia historical fire polygons WFS:

   `https://openmaps.gov.bc.ca/geo/pub/WHSE_LAND_AND_NATURAL_RESOURCE.PROT_HISTORICAL_FIRE_POLYS_SP/ows`

   The query fixes WFS 2.0, the feature type, JSON output, selected properties, `count=1`, and a CQL filter containing the monitored year and registered monitoring window. The response must be a structurally consistent `FeatureCollection`: `features`, `numberReturned`, and `numberMatched` must agree and any returned item must be a `Feature`. Only the derived `numberMatched > 0` boolean is consequential; exact counts and feature contents are not stored.

The verified Studionet scenario used Verra's July 31, 2023 BigCoast article (`canadas-burning-forests-remind-us-why-we-need-carbon-crediting`, post ID `37271`) and project reference VCS 3018. The article names the `BigCoast Forest Climate Initiative` and supports `LIKELY_LOSS`, not `CONFIRMED_REVERSAL`, because its stated loss was still awaiting exact quantification.

## Domain model

### Project record

- `project_key`: deterministic `VCS:<registry_project_id>:<sha256>`, where the full SHA-256 commits to the exact ID, name, monitoring window and first monitor year.
- `registry_project_id`: 1-10 ASCII digits.
- `project_name`: bounded display and evidence-matching name.
- `min_lon_e6`, `min_lat_e6`, `max_lon_e6`, `max_lat_e6`: immutable signed microdegrees.
- `next_monitor_year`: next completed calendar year that may be assessed.
- `status`: `UNASSESSED`, `HEALTHY`, `WATCH`, or `REVERSED`.
- `latest_epoch`: number of successful consensus-bound epochs.
- `created_at`, `last_checked_at`: deterministic transaction timestamps.

Registration validates coordinate order, British Columbia bounds, a maximum 6-degree longitude span, a maximum 4-degree latitude span, bounded strings, and `first_monitor_year < current UTC year`. It then requires validator consensus on the exact public registry identity before writing state. The caller-selected box is a BC monitoring window, not a claimed Verra project boundary. Duplicate configuration fingerprints are rejected; another configuration receives another key and cannot occupy the correct configuration's key. Records have no owner or mutable configuration.

### Monitoring epoch

- project key and sequential epoch number.
- completed `monitor_year`.
- caller address and transaction timestamp.
- validated Verra notice slug and exact Verra post ID.
- `hazard_present`.
- exact `registry_event`.
- deterministically derived `epoch_outcome`.
- resulting effective project status.

Failed retrieval, malformed data, insufficient evidence, execution failure or validator disagreement writes no epoch and does not advance `next_monitor_year`.

## Closed decisions

`registry_event`:

- `NO_REVERSAL`: the cited official evidence explicitly supports no qualifying loss or reversal for the monitored project and year. Silence is insufficient.
- `LIKELY_LOSS`: the evidence reports a possible, likely or not-yet-quantified loss.
- `CONFIRMED_REVERSAL`: the evidence explicitly confirms a reversal for the monitored project and year.
- `INSUFFICIENT_EVIDENCE`: the notice is silent, irrelevant or ambiguous, or does not uniquely support one of the three state-bearing events. Consensus may agree on this value, but the contract rejects the monitoring call before any write.

`hazard_present` is deterministic: `true` only when the fixed BC WFS query reports at least one historical fire polygon intersecting the registered box for the monitored year. It is a regional hazard signal, not proof that the carbon project itself burned.

`epoch_outcome` is derived by the contract:

1. `CONFIRMED_REVERSAL` -> `REVERSAL`.
2. `LIKELY_LOSS` -> `WATCH`.
3. `NO_REVERSAL` plus `hazard_present=true` -> `WATCH`.
4. Otherwise -> `CLEAN`.

## State transitions

| Previous | CLEAN | WATCH | REVERSAL |
|---|---|---|---|
| UNASSESSED | HEALTHY | WATCH | REVERSED |
| HEALTHY | HEALTHY | WATCH | REVERSED |
| WATCH | WATCH | WATCH | REVERSED |
| REVERSED | REVERSED | REVERSED | REVERSED |

`WATCH` and `REVERSED` are sticky in the MVP. No later silence or clean regional query can erase an adverse state. Compensation and recovery require a separately approved protocol that binds a resolution to the exact reversal; they are intentionally absent.

## Public API

Write methods:

- `register_project(registry_project_id, project_name, min_lon_e6, min_lat_e6, max_lon_e6, max_lat_e6, first_monitor_year) -> str`
- `monitor_project(project_key, verra_notice_slug) -> u32`

View methods:

- `read_permanence(project_key)` returns existence, status, next year, latest epoch and timestamps.
- `read_latest_epoch(project_key)` returns the last exact decision tuple and derived state.
- `read_epoch(project_key, epoch_number)` returns immutable epoch evidence.
- `can_use_as_healthy_backing(project_key) -> bool` is true only for `HEALTHY`.

Consumers must also wait for transaction `FINALIZED`, execution `SUCCESS`, and state readback before acting.

## Consensus flow

Registration has its own nondeterministic consensus gate. The leader and validators independently render the fixed public Verra Registry detail URL using `mode="text"` and `wait_after_loaded="10s"`, validate the exact ID/name and Canada/BC fields, and exact-compare the closed identity object. State is created only after this gate succeeds.

Before the nondeterministic block, storage values are copied to primitives. The leader:

1. Builds the two fixed-origin URLs.
2. Fetches each source once and rejects non-2xx, oversized or malformed responses.
3. Requires exactly one Verra post, the requested slug, a bounded numeric post ID, a complete stdlib-parsed ISO datetime whose year exactly equals `monitor_year`, and a bounded content excerpt that contains the registered project name.
4. Validates the WFS `FeatureCollection`, count/list consistency and feature types, then derives `hazard_present` from `numberMatched`.
5. Canonical-JSON encodes the untrusted excerpt and asks the LLM for only `registry_event`.
6. Returns only `verra_post_id`, `hazard_present`, and `registry_event`.

The validator checks the leader result type before reading calldata, independently repeats the same evidence flow, validates the closed schema, and exact-compares all three fields. Unknown keys, scores, confidence, rationale, malformed enums and uncertain error equivalence are rejected. State changes happen only after consensus.

## Consensus Binding Matrix

| field | source | stored? | downstream effect | validator check | binding mode | differential test |
|---|---|---:|---|---|---|---|
| registration identity | Verra Registry detail | yes | admission of exact ID/name/configuration | independent render and exact comparison | exact | ID, name or province change fails |
| `verra_post_id` | Verra API | yes | evidence identity | independent refetch and exact comparison | exact | different post IDs cannot both pass |
| `registry_event` | Verra content | yes | WATCH/REVERSED decision | independent refetch, classification and exact comparison | exact | LIKELY_LOSS vs CONFIRMED_REVERSAL |
| `hazard_present` | BC WFS | yes | WATCH eligibility | independent query and exact boolean comparison | exact | false vs true |
| `epoch_outcome` | decision table | yes | transition input | contract recomputation | deterministic | every tuple maps to one outcome |
| `status` | previous state + outcome | yes | oracle response | contract recomputation | deterministic | REVERSED plus CLEAN remains REVERSED |
| `monitor_year` | sequential project state | yes | evidence window | notice year must equal exact next year | deterministic | wrong notice year and current-year monitoring rejected |

## Validation and security

- No arbitrary URL, redirect target, secret, API key or private evidence.
- Verra slug is lowercase ASCII letters, digits and single hyphens only; traversal, separators, query syntax and fragments are rejected.
- Project names, IDs, responses, excerpts, prompts and LLM outputs are bounded.
- Fetched content is hostile evidence and is canonical-JSON encoded, never interpolated as instructions.
- The evidence cannot add URLs, tools, fields or policies.
- Only completed years may be monitored and years must advance sequentially.
- A notice dated for another year is rejected even if its content names the project.
- External failure, malformed output and disagreement rollback with no write.
- No floating-point value, count, score, confidence, rationale or model metadata affects state.
- No value transfer exists.

## Tests

- Valid and duplicate registration; exact registry-identity consensus and ID/name/province differentials; project ID, name and monitoring-window boundaries.
- Exact registry render URL, text mode and 10-second wait for both leader and validator.
- Invalid first year, wrong notice year and current-year monitoring rejection with unchanged state.
- Same-year malformed ISO datetime rejection with unchanged state/year.
- Fixed URL construction and hostile slug rejection.
- Exact classification schema; missing, extra, unknown and invented fields.
- Web, JSON, WFS structural, LLM schema, insufficient-evidence and consensus failure paths with rollback/no-write.
- Independent validator agreement and each true one-variable disagreement.
- Full transition table, including sticky WATCH and REVERSED.
- Prompt-injection evidence cannot alter schema, URL or policy.
- Historical epochs remain immutable and views match stored state.
- Strict mocks and pickling checks under Direct Mode.

Windows static verification:

```powershell
$env:PYTHONIOENCODING='utf-8'
$env:PYTHONUTF8='1'
$env:PYTHONDONTWRITEBYTECODE='1'
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\genvm-lint.exe check contracts\terra_shield_permanence_oracle.py
.\.venv\Scripts\genvm-lint.exe typecheck contracts\terra_shield_permanence_oracle.py
.\.venv\Scripts\genvm-lint.exe schema contracts\terra_shield_permanence_oracle.py
```

Direct Mode verification in an isolated Python 3.13 POSIX environment:

```bash
uv pip check --python .venv/bin/python
genvm-lint check contracts/terra_shield_permanence_oracle.py
genvm-lint typecheck contracts/terra_shield_permanence_oracle.py
genvm-lint schema contracts/terra_shield_permanence_oracle.py
python -m pytest -q -W error -p no:cacheprovider tests/test_terra_shield_permanence_oracle.py
```

Verified result for this revision: `31 passed in 1.25s`; isolated POSIX package check and Direct Mode tests passed, and Windows package check, lint, semantic validation, typecheck and schema extraction all exited `0`. Native Windows Direct Mode is not claimed because `genlayer-test==0.29.2` attempts to unlink an open temporary file descriptor; the unmodified suite was replayed under WSL2/POSIX instead of patching the framework or suppressing cleanup errors.

Studionet integration and consensus transactions passed on the deployment below; they complement rather than replace Direct Mode tests.

## Deployments

- **Studionet:** `0xba04dC5a5B6E673632f3cc744c103bbEfFf2740d` ([View on Explorer](https://explorer-studio.genlayer.com/address/0xba04dC5a5B6E673632f3cc744c103bbEfFf2740d))

## Reusable integrations

- Carbon-backed collateral admission through `can_use_as_healthy_backing`.
- Marketplace risk gating through `read_permanence`.
- Insurance intake and portfolio monitoring through the latest immutable epoch.

The oracle is neither ownership evidence nor a payout decision.

## Consensus Engineering Lessons

- Bind every stored external decision field, not merely the final status; the validator exact-compares the post ID, hazard boolean and registry event.
- Canonical JSON keeps hostile registry text in a data boundary, while a closed one-field response prevents model commentary from entering state.
- Registration binds the official ID and exact name before storing configuration; hashing the complete configuration prevents an incorrect first write from occupying the correct configuration's key.
- Regional fire counts are unstable detail, so the contract validates response structure but binds only the deterministic `numberMatched > 0` boolean needed by its policy.
- Sticky adverse states prevent a later clean or silent source response from erasing previously accepted risk evidence.
- A successful local call is insufficient evidence: downstream consumers must wait for `FINALIZED`, execution `SUCCESS` and state readback.

## Limitations

- MVP coverage is Verra VCS projects monitored against British Columbia fire data.
- The registry gate verifies the public record's identity and province only; it does not certify the project's lifecycle status, credit issuance or eligibility.
- The caller-selected bounding box is a BC monitoring window. It is not sourced from Verra and a matching fire intersection is a regional warning signal, not a project-boundary determination.
- Public sources may be corrected, delayed or unavailable.
- `HEALTHY` only means the exact approved evidence supports no qualifying reversal and no matching regional fire polygon for that completed year.
- WATCH and REVERSED recovery, compensation, quantified tonnes and polygon-level project boundaries are outside the MVP.

## Repository structure

```text
contracts/terra_shield_permanence_oracle.py
tests/test_terra_shield_permanence_oracle.py
README.md
LICENSE
.gitignore
```

## License

MIT
