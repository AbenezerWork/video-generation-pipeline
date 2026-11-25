# Vidpipe

Vidpipe turns a written brief into a narrated video in one or more languages by passing the work through a fixed sequence of stages, each handled by a swappable provider.

## Language

### Projects and runs

**Project**:
A folder holding one video's brief, project config, bible and everything generated for it.
_Avoid_: Workspace, job

**Project config**:
The settings that choose providers and shape the output: languages, visuals mode, resolution, gates, subtitles and mix. It does not include the brief or the bible.
_Avoid_: Settings, configuration (unqualified), YAML

**Run**:
One pass through the stages of a project, from start or resume up to a chosen stage. A project has at most one run in progress.
_Avoid_: Job, execution, build

**Run state**:
What a run in progress is doing right now: which stage, how far through it, and whether it is running, paused or failed.
_Avoid_: Progress, status file

**Pending change**:
A project config edit saved while a run is in progress. It takes effect on the next run; the run in progress keeps the config it started with.
_Avoid_: Draft, unsaved change

**Stop**:
Ending a run after the artifact in progress finishes, so no finished work is lost.
_Avoid_: Cancel, abort (those mean discarding the artifact in progress)

### Stages and providers

**Stage**:
One of the ten fixed steps of a run, from brief to assembly.
_Avoid_: Step, phase, task

**Provider**:
The tool or model a stage uses to do its work, chosen in the project config.
_Avoid_: Adapter, backend, engine, model

**Gate**:
A pause after a stage that holds the run until someone approves that stage's outputs.
_Avoid_: Checkpoint, approval step
