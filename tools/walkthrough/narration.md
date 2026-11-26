# vidpipe walkthrough narration

Each heading identifies one beat in build.py. The empty demo clip beat plays the film audio.

## title
I built vidpipe to turn a written brief into a narrated, scored and subtitled short film. I'll show how the stages fit together, why the voice sets the pace, and what happens when I change one line of the storyboard.

## film
This is The Lion's Whisker, an Ethiopian folk tale, in landscape and portrait. Both final cuts have Amharic narration, English subtitles, an original score and an AI end card. Three test viewers found the earlier voice robotic, so I switched the Amharic narration to Addis AI.

## arch-stages
A project starts with a brief, a YAML config, and a bible describing the characters, places and look. Vidpipe walks it through ten stages in four phases. Write the words: brief, script, translation and storyboard. Give them a voice: narration and fit planning. Make the pictures: keyframes and moving shots. Then music and assembly.

## arch-contracts
Storyboard dot JSON is the contract between the stages. It carries the shots, narration, visual prompts and music cues. The runner validates it and writes typed JSON for downstream stages. Every model sits behind a provider interface. Here Addis AI speaks Amharic, Edge speaks English, and ComfyUI runs the picture and music models. Swapping providers is a config change, backed by shared conformance tests.

## prompt-research
I revised the prompts after checking the model documentation against our renders. For FLUX, I put the subject first and describe what belongs in the frame, including where people stand. For Wan, I start with the camera move and describe what changes over the next few seconds. The input image already establishes the scene.

## arch-ledger
Each artifact declares its inputs: files, text, provider settings and seed. Same hash, the artifact is reused. New hash, that artifact is rebuilt. The ledger records what each artifact used. Runs dot JSON L logs each model call with the model, parameters, seed, latency and cost. That one mechanism supports caching and crash recovery.

## decision-problem
The hard decision was making the picture fit the voice. Narration runs first. Wan generates clips of two to five seconds, and each second of video costs close to forty seconds on my laptop GPU. In an earlier run, the first English line alone lasted five point six six seconds.

## decision-options
I could freeze the last frame, stretch the voice, or generate separate clips for each language. Instead, the fit planner adjusts clip speed within a bounded range. Only when that isn't enough does it split the line at a natural pause, including Amharic punctuation, and start the next clip from the last frame.

## decision-plan
One shared set of clips can serve both languages. Vidpipe plan shows which language drives the clip, how fast each cut plays it, and whether the shot needs a continuation.

## demo-baseline
Here's a scratch copy of the finished landscape project. I run the pipeline unchanged. All ten stages report skipped, and the model call log stays empty.

## demo-boundary
My first edit shortened the line from three point five three to three point three four seconds. That moved the requested clip from three point seven five to three point five seconds. The offline guard stopped the video request. The log shows exactly where it stopped.

## demo-edit
On a fresh copy, I change just one English line in storyboard dot JSON. In shot fifteen, the elder still gives the same advice. I replace boy with child.

## demo-run
I run the same command. Script refreshes from the storyboard, one English narration clip regenerates, and the fit plan updates. This time the source clip stays at three point seven five seconds. Keyframes, video and music are all reused. Assembly updates both cuts because both carry the English subtitle.

## demo-ledger
Runs dot JSON L shows one successful call, to the Edge voice for English shot fifteen. The ledger shows a new text hash and a new audio duration. The file hashes confirm that every keyframe, moving clip and the score were reused. Only one shot needed new model output.

## demo-result
Here's the English cut. It's the same generated picture, with the new line.

## demo-clip

## close
Vidpipe makes the cost of a storyboard edit visible. The fit plan tells me when a voice change needs new footage, and the ledger and model call log show what actually ran.
