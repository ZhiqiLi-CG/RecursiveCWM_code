# RCWM public delivery and log contract — version 2

This contract governs all new root and child solves. It regulates deliverables, not
which objects to group or how many descendants to create. Modeling source files
and helper structure may vary; the public paths and JSON keys below may not.

## Node inputs and ownership

A run is `runs/<run-id>/`; its root is `fractal/scene/`. Node IDs may be flat or
nested, using letters, digits, underscores, hyphens and `/`. A child ID is always
resolved from this run's `fractal/`, never relative to a parent node. Nodes have
one parent; no shared ownership or cycles. Physical nesting need not encode the
graph. The runner supplies `target.png`, `view.json`, `brief.md`, inherited
`manifest.json` and `task.md`; preserve their meaning and locked shared camera.
`manifest.json` records inherited provenance; it is NOT the output manifest.

`children.json` is a JSON array of pending child node IDs. Prepare child inputs
before requesting them, then end your session for the runner. An empty array
means no pending work, not no historical children. List all delivered direct
children in `part.json`. Reopen an existing owner rather than inventing a new ID
for a revision. Do not request children when no parent integration cycle remains.

## Required delivery layout at EVERY node

```
fractal/<node-id>/
  part.json                       # delivery candidate, strict schema v2
  account.md                      # whole/parts/whole decisions and limitations
  index.html                      # root viewer required; optional for children
  src/                            # suggested, not mandatory source organization
  outputs/
    final.png                     # locked inherited viewport, target dimensions
    comparison.png                # target left, final right, equal scale
    overlay.png                   # 50/50 target/final blend
    compass/000.png
    compass/090.png
    compass/180.png
    compass/270.png
    validation.json               # RUNNER-owned validation result, not self-certification
    final-hires.png                # optional, same view, never the scoring default
  work/                           # drafts, alternate renders, exploratory scripts
  logs/                           # RUNNER-owned (see below)
  result.json                     # RUNNER-owned node status
```

Root final.png is exactly the original reference resolution. Child final.png is
exactly its target.png resolution, including the inherited crop magnification.
Do not silently resize a different camera view or replace it with a high-resolution
presentation image. Comparisons must be 2W x H; overlays W x H. The four compass
images share a viewport size and show the actual 0/90/180/270-degree azimuth offsets
around a documented common target. Record actual poses/projection/framing and the
observed rendering backend in account.md or metadata. Wider framing for completion
inspection is allowed and must be documented. Extra angles belong in work/.
No GPU or X-display availability is assumed by this contract.

`part.json` must use this shape (JSON Schema: `schemas/part-v2.schema.json`):

```json
{
  "schema_version": 2,
  "node_id": "scene",
  "parent_id": null,
  "module": "src/scene.js",
  "export": "buildScene",
  "children": ["houses", "towers"],
  "account": "account.md",
  "viewer": "index.html",
  "outputs": {
    "final": "outputs/final.png",
    "comparison": "outputs/comparison.png",
    "overlay": "outputs/overlay.png",
    "compass": ["outputs/compass/000.png", "outputs/compass/090.png",
                "outputs/compass/180.png", "outputs/compass/270.png"]
  }
}
```

Children use their real node_id and parent_id; only scene uses parent_id null.
Every path in the manifest is node-relative, except children which are run-scoped
IDs. No absolute paths or `..`. `module` must identify a real .js/.mjs file;
`export` is an explicit JavaScript export identifier, agreed with the parent.
Do not substitute `entrypoint`, `component`, `entry`, `main`, or `file` for module.
Optional extra information goes under `metadata`, an object. Root viewer must be
index.html. Source helper filenames and build function arguments remain flexible.

Use `tools/publish_delivery.py <node-directory> --module <relative.js> --export <name>
--parent <node-id-or-dash> --children <IDs...> --final <relative.png>
--compass <000.png> <090.png> <180.png> <270.png>` with the runtime Python.
Paths supplied to this helper are relative to the node. It copies the selected
images, creates the comparison and overlay, writes canonical part.json and checks
packaging. It does NOT launch a browser or infer which image is final. The helper
never marks the node completed; runner validation is authoritative. Write the
account and root viewer before publishing. Finish the model session after publishing.

## Completion and failure

The runner requires a zero Codex process exit, valid packaging, and successfully
validated direct children. It checks the dependency tree recursively: a child's
file merely existing is insufficient. It seals current source/output/reference/
camera hashes in outputs/validation.json and writes node result.json. Only then
is status completed. The root also produces run-level result.json with canonical
final-image, viewer, manifest and log paths. Invalid or changed seals cause readers
to reject completed status. Keep additional local runtime assets in src/ when they
must be tracked with the implementation; hashes cover root source files and src/.

Validation is packaging/dependency-integrity validation. It does NOT prove visual
similarity, actual export behavior, camera pose correctness, or successful browser
execution. Render and inspect the actual program as instructed; document that
separately. A visual_stop label is no longer used as proof of success.

One packaging-only correction session is allowed by default when a successful
model call produces invalid artifacts (`RCWM_PACKAGING_REPAIRS=0..3`). It does not
consume a modeling cycle, is explicitly logged with purpose=packaging, and cannot
change JavaScript implementation files. It may fix JSON fields/paths and publish
already-rendered evidence. Missing images may therefore require a later modeling
resume rather than a packaging repair. Persistent validation failure exits nonzero.

Statuses: running, waiting_children, completed, executor_failed, child_failed,
invalid_delivery, budget_exhausted, interrupted. Provider-specific failures are not
inferred solely from raw text: executor_failed records a nonzero Codex exit and
its session log. Recovered connection warnings do not make a completed run fail.

## Canonical logs (all written by the runner)

Run-level:
- `logs/run.log`: launcher stdout/stderr when using rcwm.sh or resume_run.sh.
- `logs/runner.log`: timestamped node lifecycle summary.
- `trace/events.jsonl`: locked, append-only event stream across all nodes.
- `trace/tree.json`, `trace/recursion_report.md`: derived recursion summaries.
- `result.json`: current authoritative root result/index.

Node-level:
- `logs/codex.log`: cumulative raw Codex transcript with session separators.
- `logs/sessions/session-0001.log`, etc.: separate raw transcript per invocation;
  numbers never reset on resume. No mixing prior usage into the current session.
- `logs/events.jsonl`: that node's subset of the structured trace.
- `result.json`: current status, cycle, validated/pending children and error.

Machine-readable schemas: `schemas/event-v2.schema.json` and `schemas/result-v2.schema.json`.
Every event has schema_version=2, timestamp, invocation_id, run/node/parent IDs,
depth, cycle, event name, solver/contract/camera hashes. Session events additionally
carry session number, purpose (modeling/packaging), relative log path, model/effort
on start, and exit_code/elapsed_seconds/usage_total/transport_warning_lines on end.
Unknown usage is null, not a fabricated value. Child returns have actual exit_code
and validated delivered status; validation failures carry actionable error text.
Stop events have status/stop_reason and exit_code. Event writes are serialized with
file locks so parallel children cannot interleave partial JSON records.

`.sid`, `children.json.prev` and lock files are runner implementation state, not
public final results. Preserve them for resumption; do not use them to infer the
final dependency graph. Never put credential homes into published result bundles.

## Legacy data

The default check_part.py still reads unversioned historical manifests through the
legacy checker; --strict requires v2. New runs always require v2. Pickers preserve
legacy filename rules ONLY for unversioned data without v2 result/condition markers.
Historical runs are not renamed or rewritten automatically. Use a separate index
for archival normalization. Starting a new batch records the v2 contract hash and
code revision; it is a changed experimental condition, not an identical old run.
