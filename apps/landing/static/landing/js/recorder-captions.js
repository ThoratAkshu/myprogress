// Learning studio live captions: turn the presenter's speech into timed WebVTT captions while recording,
// using the browser's built-in speech recognition (Chrome and Edge).
window.StudioCaptions = (() => {
  const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  const pad = (value, size = 2) => String(value).padStart(size, "0");
  const stamp = seconds => {
    const total = Math.max(0, seconds);
    const hours = Math.floor(total / 3600);
    const minutes = Math.floor((total % 3600) / 60);
    const secs = Math.floor(total % 60);
    const millis = Math.floor((total % 1) * 1000);
    return `${pad(hours)}:${pad(minutes)}:${pad(secs)}.${pad(millis, 3)}`;
  };

  /*
   * clock(): seconds into the recording, pauses excluded.
   * onText(text, final): called with what is being heard, for a live preview.
   * onError(code): called when captions stop for good (for example, permission denied).
   */
  function create({ lang, clock, onText, onError }) {
    let recognition = null;
    let listening = false;
    let phraseStart = null;
    let failures = 0;
    const cues = [];

    function spawn() {
      recognition = new Recognition();
      recognition.lang = lang;
      recognition.continuous = true;
      recognition.interimResults = true;
      recognition.onresult = event => {
        for (let index = event.resultIndex; index < event.results.length; index += 1) {
          const result = event.results[index];
          const text = result[0].transcript.trim();
          if (!text) continue;
          failures = 0;
          if (phraseStart === null) phraseStart = Math.max(0, clock() - 0.6);
          if (result.isFinal) {
            cues.push({ start: phraseStart, end: Math.max(clock(), phraseStart + 1), text });
            phraseStart = null;
          }
          onText?.(text, result.isFinal);
        }
      };
      recognition.onerror = event => {
        // Give up on errors that won't fix themselves, or after repeated failures (for example, no connection).
        failures += ["no-speech", "aborted"].includes(event.error) ? 0 : 1;
        if (["not-allowed", "service-not-allowed", "language-not-supported"].includes(event.error) || failures >= 5) {
          listening = false;
          onError?.(event.error);
        }
      };
      // Browsers end recognition sessions on their own after a while; keep listening until told to stop.
      recognition.onend = () => { if (listening) setTimeout(() => { if (listening) spawn(); }, 250); };
      try {
        recognition.start();
      } catch {
        listening = false;
      }
    }

    return {
      start() {
        if (!Recognition || listening) return;
        listening = true;
        spawn();
      },
      stop() {
        listening = false;
        phraseStart = null;
        try {
          recognition?.stop();
        } catch {
          // already stopped
        }
        recognition = null;
      },
      get count() {
        return cues.length;
      },
      vtt() {
        if (!cues.length) return "";
        return `WEBVTT\n\n${cues.map((cue, index) => `${index + 1}\n${stamp(cue.start)} --> ${stamp(cue.end)}\n${cue.text}`).join("\n\n")}\n`;
      },
    };
  }

  // Languages offered for captions; the browser's own language comes first when it is not in the list.
  const LANGUAGES = [["en-IN", "English (India)"], ["en-US", "English (US)"], ["en-GB", "English (UK)"], ["hi-IN", "Hindi"], ["mr-IN", "Marathi"], ["ta-IN", "Tamil"], ["te-IN", "Telugu"], ["bn-IN", "Bengali"], ["es-ES", "Spanish"], ["de-DE", "German"], ["fr-FR", "French"]];
  return { supported: Boolean(Recognition), create, LANGUAGES, stamp };
})();
