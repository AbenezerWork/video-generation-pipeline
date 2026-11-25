# Project config changes during a run apply to the next run

A run resolves its providers from the project config when it starts, and the ledger fingerprints every artifact with the provider and options that made it. When the project config is edited while a run is in progress (for example from the graphical interface), the edit is saved at once as a pending change but the run in progress finishes on the config it started with. The interface shows what the pending change will regenerate and offers to stop and restart, which is cheap because finished artifacts are reused.

## Considered Options

- **Re-read the config at each stage boundary.** Rejected: one run would mix two configs, so its plan, cost estimate and ledger would no longer describe a single coherent setup.
- **Lock the config while a run is in progress.** Rejected: runs can last an hour, and blocking edits for that long defeats being able to change the config at any point.
