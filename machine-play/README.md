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
pytest -q                                   # about 15 s, no API calls

# Offline smoke run with a scripted agent (no tokens):
python -m machineplay run --agent scribe --out runs/smoke --lives 6
# Check that this world can show a ratchet at all (positive vs negative control, a few minutes, no tokens):
python -m machineplay sweep --agent scribe --seeds 10 --lives 16 --out runs/cal_pos
python -m machineplay sweep --agent naive-scribe --seeds 10 --lives 16 --out runs/cal_neg

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

Everything is computed from `runs/<run>/events.jsonl`. No being ever sees it. `metrics <run> --programs` also lists
every program version (a slate as written in one life) with its runs, success rate and compounds made per run.

| Metric | Meaning | A ratchet looks like |
|---|---|---|
| `frontier` | distinct compounds made by any life so far (`compounds_possible` is the ceiling) | rises faster than in the amnesia arm |
| `new`, `max_tier` | compounds no earlier life made; the deepest made in this life | stays above zero; climbs |
| `remade` | share of the previous life's compounds made again | high **with** `new` > 0. High with `new` = 0 is an exploitation trap |
| `iur` | share of turns that touched writing or code from an earlier life | above zero |
| `slates`, `code`, `derived` | slates written, with code, and descending from earlier writing (matched by content) | `derived` > 0 every life |
| `runs`, `frame_runs`, `uses` | runs a being started (ok/total), runs frames made alone, `use()` of inherited slates | stage 2 and 3 machinery in use |
| `inh_calls`, `inh_made` | world calls and compounds made by programs **written in earlier lives** | capability carried by code |
| `longest_chain` | longest chain of writes, each descending from an earlier life's writing | keeps lengthening |
| `reused_slates` | slates touched by 3 or more later lives | inherited tools |
| `improved_derivations` | derived programs that make more per run, or fail less, than the version they came from | tools improving, not just copied |

**Controls.**
- **Amnesia arm** (`--arm amnesia`): the same seed, but the world is rebuilt between lives. Its frontier is the union of
  independent lives, which is a strong baseline: a lineage has to beat parallel independent search.
- **Mute arm** (`--arm mute`, or `sweep --control mute`): every object persists, but all writing is erased between
  lives. Inherit vs amnesia mixes two inheritances, things and words; inherit vs mute isolates what the words add.
  In the scripted runs this mattered: at stage 0 the whole inherit-vs-amnesia "ratchet" (+1.8) came from leftover
  compounds, not writing. And at stage 1 objects *without* records were worse than a fresh world (inherit vs mute
  +7.6 ± 1.9 against +4.4 ± 1.5 vs amnesia, 10 seeds), because newcomers waste tries on unexplained compounds.
- **Several seeds** (`sweep`). One seed per arm is noise: the negative control shows a "ratchet signal" on about
  40% of single seeds. `sweep` runs both arms over N seeds and calls RATCHET only if the mean gap widens and the
  final mean gap is more than two standard errors above zero. It reuses finished runs, so it resumes.
- **Archaeology** (`eval`): fresh beings in fresh worlds carrying only life *k*'s writing. A rising curve over *k*
  means the artifacts themselves improved. For the scripted scribe it is flat (about 6 compounds per life from
  life 0's writing or life 15's): its culture works, but its writing stops improving early.
- **Ceiling warning.** `compare` and `sweep` warn when both arms are near `compounds_possible`. At that point the
  control catches up whatever the culture does.

```bash
python -m machineplay sweep --agent claude --stage 1 --seeds 5 --lives 12 --out runs/sweep_s1
```

### Scripted controls, and what they showed

The scripted agents navigate by coordinates and do exactly what their code says, so they predict nothing about
Claude beings. They exist to show that the world and the metrics can tell a ratchet from its absence **before**
you spend money.

| Agent | Role | Stage 1, default world, 10 seeds × 16 lives |
|---|---|---|
| `scribe` | positive control: keeps one compressed RECIPEBOOK up to date in place, upgrades an inherited first-draft CRAFTER, builds on its deepest compounds before re-making anything; uses `use()` and frames at stage 2 and a mantle at stage 3 | final gap **+4.4 ± 1.1**, 8/10 seeds: **RATCHET** |
| `naive-scribe` | negative control: reuses inherited code but treats inherited recipes only as pairs to skip | **+0.6 ± 0.6**, 4/10 seeds: **NO RATCHET** |
| `wanderer` | floor: never writes | — |

Stage 3 (6 seeds): +4.3 ± 1.6, RATCHET, but near the ceiling of the default world. With `--set n_elements=16
--set max_tier=8`: +4.3 ± 1.4, RATCHET. Stage 2: +1.8 ± 1.0, positive but not significant; frames contribute almost
nothing (about 0.02 compounds per run), because their 4 m arm rarely reaches enough cubes.

What it took to get a positive control. Each item is a pressure real beings will face too:
1. **Exploitation trap.** A first version rebuilt the deepest known compound before anything else. Its inherited
   code tripled output per run, yet it lost to the amnesia arm on every seed in bigger worlds: it re-made the past
   (`remade` near 1) and stopped discovering (`new` near 0). Building on the frontier first fixed it.
2. **Slate overflow.** A plain recipe list fills a 4,000-character slate after about 80 entries. Kept successes-first,
   it silently dropped the tried-and-failed pairs, so later lives re-tried known failures as if they were new (only
   4–8 of about 97 attempts per life were genuinely new). An indexed, compressed book (about 650 tried pairs per
   slate, still valid Python for `use()`) made inheritance pay. How Claude beings compress, split across slates,
   and choose what to forget is one of the most interesting things to watch.
3. **Lineage detection.** Links between writing were first inferred from a 15-turn window and missed real
   derivations (read at turn 8, written at turn 25). They are now matched by content: the writing read earlier in
   the life whose words survive best in the new text, including rewrites in place.

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
  agents/scripted.py  wanderer, naive-scribe (negative control), scribe (positive control, every stage)
  lineage.py       birth, life, death, erosion; amnesia and archaeology worlds; resume
  metrics.py       per-life and per-run ratchet metrics, arm comparison
  cli.py           run / sweep / eval / metrics / compare / show
tests/             world rules, sandbox limits, stages 2 and 3, lineage and controls, the Claude harness (fake client)
```

## A first 48 hours

1. `pytest -q`, then one scribe smoke run, to confirm the sandbox works on your machine (`unshare` may be unavailable;
   set `MACHINEPLAY_NO_UNSHARE=1` to skip it).
2. Run **one Claude life at stage 1** with `--lives 1` and read `transcripts/life_0000.jsonl`. Does the being find the
   engine? Does it read the plate? Calibrate `turns_per_life` so a life can explore *and* make something.
3. Whenever you change the world's settings, re-run the scripted calibration (positive control RATCHET, negative
   control NO RATCHET) first. If the positive control can't ratchet, no being can.
4. Run `sweep --agent claude` with 3–5 seeds × 8–12 lives. Pre-register success: **at least one code slate run by 3 or more
   distinct lives, and at least one derived slate whose runs succeed more often than its parent's.**
5. Tune by symptom:
   - Nobody touches the engine within 3 lives: move it closer, or raise `look_radius`.
   - Code gets written but never reused: wear isn't salient, or lives are too short for reading to pay off; raise `turns_per_life`.
   - The inherit and amnesia arms look the same: inspect `iur` before blaming the beings.
   - `remade` high with `new` at zero: an exploitation trap; the lineage re-makes its inheritance and stops exploring.
6. Move to stage 2 only once stage 1 shows reuse across lives, and to stage 3 only once libraries appear.
