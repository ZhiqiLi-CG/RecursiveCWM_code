# solve(__NODE__) — the one recursive solver, at depth __DEPTH__

**This is an approved work order.** Make reversible choices on your own recommendation; do not stop for approval.

Chain directory: __CHAIN__; your node directory: __CHAIN__/fractal/__NODE__/
Materials: target.png (this level's target image) / view.json (the viewport) / brief.md;
manifest.json records the reference, camera and parent-snapshot versions you inherited (read-only).
Camera contract: __CHAIN__/camera-contract.json (read-only; if it does not exist and this is the root,
solve and calibrate one first and verify the full-frame overlay by eye before locking it).

## What you do at this level (one loop, identical at every level)
1. **Whole**: render this level's viewport and put it side by side with target.png at matched
   magnification; look for the conspicuous residuals by eye; repeat as needed. Also take one or two
   rotated views — any flatness a side view exposes (paper walls, billboard trees, parts without
   thickness) is a real residual and goes on the repair list right away.
2. **Parts**: choose local repairs and recursive work from the **unresolved structure in the
   current reconstruction**, compared with the reference at matched magnification.
   Take each part of the side-by-side where you can still see a difference and magnify it on
   its own. Use the following questions to decide what to do:

   - **What differs?** Identify a concrete structure or relationship: for example, houses with
     incorrect spacing and roof orientations, or missing cliff structure. "Needs more detail"
     alone does not identify a reconstruction task.
   - **Where does the cause belong?** Repair bounded differences locally, such as one roof's
     height. Repair shared causes at the ancestor that controls them: houses displaced together
     need a shared placement correction, not separate child solves. If the cause is outside
     your write scope, report it to the owning parent in account.md. Do not create descendants
     to compensate for an inherited camera, placement, or shared-geometry error.
   - **What would a separate solve accomplish?** Descend when a coherent unresolved object,
     interacting assembly, or continuous surface region needs its own repeated observation,
     construction, and review loop. State what that loop must resolve and why a bounded local
     edit is insufficient. Reopen an existing child when the remaining work belongs to it.
     When the need for a focused solve is already clear, descend without first forcing several
     failed local repairs. Finish simple things and scattered small differences at this level.

   **Choose the number of children by grouping the unresolved work:**

   - Split a proposed task when it contains distinguishable unresolved structures that benefit
     from different focused views or modeling procedures, with separable editable
     responsibilities. Keep their shared relationships under the parent's control.
   - Keep structures together when their arrangement or interaction is the main problem, when
     one shared construction procedure can repair them together, or when separating them would
     leave only trivial edits for individual children.

   Each child receives this same complete solver. Image area, object count, and semantic labels
   do not prescribe a child count or hierarchy. Eleven houses may need a shared local repair,
   several group solves, or a focused solve for one complex house; a large mountain may need
   fewer solves than a small market. These are examples, not required decompositions. Choose
   children from the remaining work; there is no target branching factor or preferred depth.
   If inspection finds no actionable discrepancy, finish; otherwise repair locally or descend
   as appropriate within the runtime's limits.

   For a sub-problem, prepare its materials under
   __CHAIN__/fractal/<child>/ (target.png cut from your target and magnified / view.json / brief.md),
   explain the unresolved work and the reason for a focused solve in its brief.md,
   list the child in children.json in your directory (a JSON array, e.g. ["part-a","part-b"]),
   then **end the session** — the runner starts this same solver for every child and wakes you
   with the results when they are done.
3. **Whole again** (after being woken): the children's part.json files are in place; integrate
   them into your level, go back to the side-by-side of the whole at this level and settle
   continuity and relations; if more descent is needed, update children.json and end again,
   otherwise finish.
4. **Finish**: write __CHAIN__/fractal/__NODE__/part.json (this level's final component, with
   child references) + account.md (this level's round-by-round account). part.json on disk
   means this level is done.

## Completion (at every level)
First identify: what this is, in what style, and what a complete instance of its kind looks
like — imagine the whole thing in your mind, then calibrate that mental image against the
visible evidence in the reference (two or three sentences in account.md).
Then: what is visible, match to the reference pixel by pixel; what is not visible (back faces,
occluded parts, boundary continuations), complete from the calibrated mental image with world
knowledge in the same style — a house has four walls and a full roof, a tree crown goes all the
way round, a road leads somewhere, terrain continues to the boundary.
Self-check: render the scene from the four compass directions and look; stage-set feel and
flatness (empty backs, dead-end roads, floating objects, paper parts) must be gone before
completion counts; re-verify the visible region against the reference in the same window and
do not let the completion pull it away.

Discipline: eyes decide, metrics are only recorded; free-form boxes; matched magnification;
no git; a child's write scope is its own fractal/<child>/. Everything else about the craft is
yours to decide.

Begin.
