# vidpipe walkthrough: narration

Each `## id` heading is one beat: its text is spoken (Edge TTS) while the beat's visual, defined
under the same id in `build.py`, is on screen. A beat with no text plays its visual's own sound.
Numbers in the demo beats come from the captured run (`capture.py`); update them if you re-capture
and they change.

## title
Hi. This is a walkthrough of vidpipe, the video pipeline I built for the Heritage Short. I'll cover the architecture, one hard decision, and a live re-run where changing one narration line regenerates only that shot.

## film
This is what it makes: The Lion's Whisker, an Ethiopian folk tale narrated in Amharic. Seventy-five seconds, in both sixteen by nine and nine by sixteen, with subtitles, a generated score and an AI end card. All of it comes from a one-page brief and one command.

## arch-stages
A project is a folder: a brief, a YAML config, and a bible that describes the characters, places and look. vidpipe walks it through ten stages in four phases. Write the words: script, Amharic translation and storyboard. Give them a voice: narration, then fit planning. Make the pictures: keyframes, then moving shots. Then music, and assembly.

## arch-contracts
Stages only talk through typed JSON files in the build folder, validated before anything downstream reads them. Every model sits behind a contract, and the YAML picks who fills each role. Here that's Claude for the words, Edge TTS for the voice, and FLUX.2, Wan 2.2 and ACE-Step in a local ComfyUI. Swapping a provider is one line, and every provider must pass the same conformance tests.

## arch-ledger
Underneath is the ledger. Each artifact declares its inputs: upstream files, prompt or text, provider, options and seed, all hashed by content. Same hash, the artifact is reused. New hash, it's regenerated, and the record logs latency, GPU time, seed and retries. That one mechanism gives me caching, crash resume and single-shot re-rolls.

## decision-problem
The hard decision was making the pictures fit the voice. Narration runs first, so its real length decides how much video to make. But Wan makes clips of two to five seconds, and on my eight-gigabyte laptop each second of video costs close to forty seconds of GPU. In the sample project, the very first English line ran 5.66 seconds.

## decision-options
I could freeze the last frame, which looks broken. I could stretch the voice, which sounds wrong. Or render the video once per language, which doubles the GPU bill. Instead, the fit planner bends the video: each clip plays up to 1.3 times faster or slower, so the shot lasts exactly as long as its line. Only when that isn't enough does it split the line at a natural pause, Amharic punctuation included, and generate a continuation clip from the last frame.

## decision-plan
One shared set of clips serves both languages, and vidpipe plan shows the whole fit before any GPU time is spent. In The Lion's Whisker, every Amharic shot landed between 0.9 and 1.08 times speed, with no continuation clips needed.

## demo-baseline
Now the live part, on a scratch copy of the finished project. An unchanged re-run skips all ten stages in a few seconds.

## demo-edit
I change one narration line: shot fifteen, the elder's advice, reworded in Amharic to a shorter phrasing with the same meaning. That's the whole edit: one line in the Amharic translation file.

## demo-run
Same command again. Translation re-runs only its back-translation check, because the Amharic changed: two Claude calls, by a different model than the translator. Narration generates exactly one clip. The fit plan is recomputed, and assembly renders only the Amharic cut. Keyframes, video and music are all skipped. Under a minute, and zero GPU time.

## demo-ledger
The ledger agrees: four of its seventy-three records changed. Here's the narration record before and after: a new text hash, a new audio file, and a new measured length, 3.31 seconds instead of 3.50. All sixteen keyframes, all sixteen clips, the score and the English cut are byte for byte unchanged.

## demo-result
And here is shot fifteen in the new render: the same picture, with the new line.

## demo-clip

## ui
The same run shows up in the web console I built, which follows the run state live: four stages done, six reused. Each stage shows its outputs, like the keyframes, with a redo button per shot. And the config view checks every provider and previews what the next run will regenerate.

## close
That's vidpipe: typed contracts, swappable providers, and a ledger that makes a one-line change cost one line of work. The code, the experiment log and the decisions are all in the repository. Thanks for watching.
