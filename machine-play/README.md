# Machine Play

Generations of beings live and die one at a time in a small 3D world. Each death wipes the mind. The only things that
survive are what a being leaves in the world: cubes made through a hidden chemistry, words on three 200-character
inscription stones, and, from stage 1 on, **slates holding up to 4,000 characters of text or Python that an engine in
the world can run**. Beings are never told they belong to a lineage, never told they will die, and never given a goal.

The question: does capability ratchet upward across lives that never meet, purely through what they leave behind, up
to and including software and improved versions of the beings' own working methods?

## Design in three rules

1. **Code is a physical object.** A program is a slate: it can be found, carried, copied, overwritten, lost, and worn down.
2. **Running code is a physical process.** The engine runs a slate *as the being's own body*: every `world.*` call goes
   through the same rules and costs as acting by hand. A program gains no new powers, only leverage. Because lifespan is
   counted in **deliberations** (model calls), a program that makes 50 moves in one deliberation is worth a great deal.
3. **Use leaves a mark.** Slates that later lives read or run become visibly *worn*. Slates nobody touches for a while
   *erode* character by character. Selection, with no external goal.

## Stages

| Stage | New affordances | What a being can leave behind |
|---|---|---|
| 0 | chemistry, 3 stones of 200 characters (the original system) | compound cubes, short notes |
| 1 | slates (4,000 characters, titled by their first line), the slate quarry, the **engine**, wear and erosion | manuals, maps, recipe books, **runnable tools** |
| 2 | `use('TITLE')`: import the nearest legible slate with that title; **frames** run a slate on their own, powered by compound cubes | libraries, layered toolchains, machines that keep working after their maker dies |
| 3 | **mantles**: a `#!mantle` slate with `## mind` words and `## code` `tool_*` functions that a being can `attune` to and `invoke`; `think(prompt)` inside programs | improved versions of a being's own working instructions and toolkit; tools that think |

The engine's cast-iron plate (`inspect engine`) is the only documentation the world gives. It reads like physics, not
like a goal.

## Quick start

```bash
cd machine-play
pip install -e '.[claude,dev]'
pytest -q                                   # about 4 s, no API calls

# Offline smoke run with a scripted agent (no tokens):
python -m machineplay run --agent scribe --out runs/smoke --lives 6

# The real thing: Claude beings, stage 1, with a matching control arm
python -m machineplay run --out runs/s1_inherit --lives 10 --stage 1 --seed 1
python -m machineplay run --out runs/s1_amnesia --lives 10 --stage 1 --seed 1 --arm amnesia
python -m machineplay compare runs/s1_inherit runs/s1_amnesia

python -m machineplay show runs/s1_inherit          # read every stone and slate in the latest world
python -m machineplay eval --snapshot runs/s1_inherit/snapshots/after_life_0009.json --out runs/dig9 --lives 3
python -m machineplay run --out runs/s1_inherit --lives 20 --resume   # extend a run
```

Credentials come from the environment (`ANTHROPIC_API_KEY`, or an `ant auth login` profile). The default mind is
`claude-opus-5-5` at `--effort medium`, with adaptive thinking (summaries saved to `runs/<run>/transcripts/`) and
server-side refusal fallbacks (`fallbacks: "default"`) turned on. Use `--fallbacks off` to disable them; they are
skipped automatically for models that don't support them. Any config field can be overridden with
`--set key=value`, for example `--set slate_chars=8000 --set turns_per_life=200`.

**Cost.** One life is `turns_per_life` model calls (150 by default). History grows within a life and is cached; old
tool results are trimmed server-side. Check the `tokens_in` / `tokens_out` columns after the first life and scale
from there before committing to a long run.

## Measuring the ratchet

Everything is computed from `runs/<run>/events.jsonl`. No being ever sees it.

| Metric | Meaning | A ratchet looks like |
|---|---|---|
| `frontier` | distinct compounds made by any life so far | keeps rising, faster than in the amnesia arm |
| `new`, `max_tier` | compounds no earlier life made; the deepest compound made in this life | stays above zero; `max_tier` climbs |
| `parity` | turn by which this life re-made everything the previous life made | falls over lives |
| `iur` | share of turns that touched writing left by an earlier life | above zero and stable |
| `code`, `runs`, `program_actions` | code slates written; engine runs (ok/total); moves made by programs | rising `program_actions` = capability carried by code |
| `derived`, `longest_chain` | writes made right after reading earlier writing; longest such chain | chains that keep lengthening = edits building on edits |
| `reused_slates` | slates touched by 3 or more distinct later lives | the first real evidence of inherited tools |
| `improved_derivations` | derived slates, run at least twice, whose runs succeed more often than their parent's | tools getting better, not just copied |

**Two controls make claims credible.**
- **Amnesia arm** (`--arm amnesia`): the same seed, but the world is rebuilt between lives. A ratchet exists only if the
  inherit arm beats the amnesia arm **and the gap widens with each life**.
- **Archaeology** (`eval`): fresh beings in fresh worlds carrying *only the writing* from life *k*'s snapshot. Plot
  frontier against *k*. A rising curve means the artifacts themselves got better, as opposed to the world simply
  accumulating cubes.

The scripted `scribe` agent shows why the controls matter. It does inherit and reuse its SEEKER program, so `iur`,
`reused_slates` and `longest_chain` all look healthy. But it skips pairs it knows about instead of building on them,
and the amnesia arm overtakes it on `frontier`. Inheritance alone is not a ratchet.

## Safety and containment

- **Sandbox.** Each run is a separate `python -I -S` process: CPU and memory rlimits, file writes forbidden
  (`RLIMIT_FSIZE=0`), an empty environment (no API key leaks into programs), a temporary working directory, and no
  network namespace (`unshare -rn`) where the kernel allows it. Builtins are whitelisted, imports are limited to pure
  modules (`math`, `json`, `re`, ...), and attribute names starting with `_` are rejected by an AST check. The process
  boundary is the real security boundary; the filtering is only a seatbelt. For unattended long runs, wrap the child in
  nsjail, gVisor or a container.
- **Budgets.** Up to 200 world calls per run (50 per frame cycle). Output is capped at 2,000 characters, but the error
  that ended a run is always shown in full. Each message from the child must arrive within a wall-clock limit. Frames
  burn charge. `think()` has a per-life token budget and returns `[silence]` once it runs out.
- **Mantles can't escape their slot.** Mantle words arrive as an appended, clearly labelled system message, capped at
  1,500 characters, one mantle per life. They never replace the frozen system prompt, and the tool list never changes
  mid-life (`invoke` dispatches techniques). Mantle code runs in the same sandbox as everything else.
- **The harness is append-only.** History is never edited (status rides in the user turn), so thinking blocks stay valid
  and the prompt cache keeps hitting.

## Layout

```
machineplay/
  config.py        every knob, one dataclass (saved as runs/<run>/config.json)
  chemistry.py     seeded hidden reaction DAG (tiers 0..max_tier)
  world.py         objects, bodies, space, all actions via World.dispatch, erosion, frames, mantles, snapshots
  sandbox/         engine host (limits, JSON-lines protocol, use() resolution) and the child process
  agents/claude.py Claude mind: one call per deliberation, one action per call, append-only history
  agents/scripted.py  wanderer and scribe: offline baselines that exercise every channel
  lineage.py       birth, life, death, erosion; amnesia and archaeology worlds; resume
  metrics.py       per-life and per-run ratchet metrics, arm comparison
  cli.py           run / eval / metrics / compare / show
tests/             world rules, sandbox limits, stages 2 and 3, lineage and controls, the Claude harness (fake client)
```

## A first 48 hours

1. `pytest -q`, then one scribe smoke run, to confirm the sandbox works on your machine (`unshare` may be unavailable;
   set `MACHINEPLAY_NO_UNSHARE=1` to skip it).
2. Run **one Claude life at stage 1** with `--lives 1` and read `transcripts/life_0000.jsonl`. Does the being find the
   engine? Does it read the plate? Calibrate `turns_per_life` so a life can explore *and* make something.
3. Run 8–10 lives × {inherit, amnesia} × 2–3 seeds. Pre-register success: **at least one code slate run by 3 or more
   distinct lives, and at least one derived slate whose runs succeed more often than its parent's.**
4. Tune by symptom:
   - Nobody touches the engine within 3 lives: move it closer, or raise `look_radius`.
   - Code gets written but never reused: wear isn't salient, or lives are too short for reading to pay off; raise `turns_per_life`.
   - The inherit and amnesia arms look the same: inspect `iur` before blaming the beings.
5. Move to stage 2 only once stage 1 shows reuse across lives, and to stage 3 only once libraries appear.
