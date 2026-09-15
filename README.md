<h1 align="center">Recursive Code World Models</h1>
<p align="center">Building Complex Worlds through Recursive Scene Programs</p>
<p align="center">Zhiqi Li · Yuxuan Liao · Bo Zhu</p>
<p align="center">
  <a href="https://arxiv.org/abs/2609.11499"><strong>Paper</strong></a> ·
  <a href="https://zhiqili-cg.github.io/RecursiveCWM/"><strong>Project Page</strong></a> ·
  <a href="https://arxiv.org/html/2609.11499v1"><strong>arXiv HTML</strong></a>
</p>

> **Status: This release is still being tested and completed and may be unstable in places.**
> **You are welcome to try it and send feedback and suggestions through GitHub issues.**

![Recursive Code World Models teaser](https://zhiqili-cg.github.io/RecursiveCWM/images/teaser.webp)

One reference image in, one executable parameterized 3D scene program (three.js) out.
A single solver instruction recurses at every scale, *whole → parts → whole again*: the root establishes the whole scene,
cuts what it cannot resolve into children, each child receives a magnified crop of the reference as its own target and
runs the same instruction, and when the children return the parent integrates their subprograms and revisits the whole.
Depth is decided by what the executing model can still see is wrong; siblings run in parallel.
Numeric scores are recorded afterwards, never used as gates.

## Quick start

Use Linux with CPython 3.12.x (with `venv`), `curl`, `tar`, `git`, and an account with access to `gpt-6-astra`.
Install the runtime below; for conda/mamba, add `--conda rcwm` to create a Python 3.12 environment.
To select an installed interpreter, add `--python /path/to/python3.12`. See [Python compatibility](docs/environment.md#python-compatibility) for the dependency constraints and recovery steps.
For dependency conflicts in an existing runtime, add `--recreate-venv` to back up and rebuild its Python environment.
The defaults use the paper's English instruction, private Codex home, `gpt-6-astra` at `high`, depth 4 and 3 cycles per node.

```bash
git clone https://github.com/ZhiqiLi-CG/RecursiveCWM_code.git
cd RecursiveCWM_code
export RCWM_ROOT="$PWD/runtime"
bash setup/setup_runtime.sh "$RCWM_ROOT"
export PATH="$RCWM_ROOT/.render-tools/node/bin:$PATH"
npm install -g @openai/codex@0.154.0
codex login
./rcwm.sh experiments/pilot-scenes/medieval-village.png medieval-village
tools/view.sh "$RCWM_ROOT/runs/medieval-village"
```

After the run finishes, open the URL printed by `tools/view.sh`; drag to orbit, right-drag to pan, and scroll to zoom.

## 🚧 TODO

- [ ] Windows support (currently Linux only: bash runner and Playwright/Chromium paths)
- [ ] Complete code review
- [ ] Prompt and skill optimization
- [ ] Efficiency (tokens, wall-clock, parallelism)
- [ ] Complete evaluation across models and reasoning efforts
- [ ] Complete evaluation on a larger dataset

## Documentation

[Complete operating guide](docs/usage.md)

[Code structure and script reference](docs/code-structure.md)

[Runtime environment](docs/environment.md)

[Paper conditions and recorded runs](docs/paper-conditions.md)

[Reproducing tables, figures, baselines, and ablations](docs/reproduce.md)

## Citation

```bibtex
@article{li2026rcwm,
  title   = {Recursive Code World Models: Building Complex Worlds through Recursive Scene Programs},
  author  = {Li, Zhiqi and Liao, Yuxuan and Zhu, Bo},
  journal = {arXiv preprint arXiv:2609.11499},
  year    = {2026}
}
```

MIT [License](LICENSE). Reference-image sources and terms: [References](experiments/pilot-scenes/REFERENCES.md).
