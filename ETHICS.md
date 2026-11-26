# AI provenance

Vidpipe assembles films from a written brief and project assets. Depending on the configured
providers, AI can generate the script, translations, storyboard, voice, images, motion and score.
A project can use an edited storyboard to supply the text and visual prompts. The sample uses
deterministic fake providers for offline testing.

Finished MP4s carry an AI-generated metadata notice. The optional end card discloses AI use
on screen. The project configuration identifies the selected providers, and the provider call
log and build ledger record the calls, seeds and settings used to produce the artifacts.
