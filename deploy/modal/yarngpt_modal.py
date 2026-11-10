"""
YarnGPT2 (Nigerian-accented TTS) on Modal: Avenza's self-hosted voice.

Deploy:   modal deploy deploy/modal/yarngpt_modal.py
          YARNGPT_GPU=T4 YARNGPT_MIN_CONTAINERS=1 modal deploy deploy/modal/yarngpt_modal.py   (options)
Test:     modal run deploy/modal/yarngpt_modal.py --text "How far, how body?" --speaker idera
Measure:  python scripts/modal_tts_probe.py   (from the Avenza repo, with YARNGPT_MODAL_URL in .env)

The web endpoint is unauthenticated: keep its URL out of git (Avenza reads YARNGPT_MODAL_URL from .env).

Speed changes from the first version (10 Nov: ~21 s warm for 4.8 s of speech on a T4):
  * float16 weights (was "auto": float32/bfloat16, and a T4 has no fast bfloat16),
  * an L4 by default (newer GPU, ~2x faster per token than a T4 for this model),
  * 2 beams for Yoruba/Igbo/Hausa instead of 5 (5 beams cost ~5x the work),
  * a warm-up generation when the container starts, so the first request is not the slow one,
  * a timing line per request in the Modal logs (chars, seconds, tokens per second),
  * optional min_containers so the GPU never goes cold during a demo (billed while on).
"""

import io
import os
import re
import sys
import time

import modal

MODEL_ID = "saheedniyi/YarnGPT2"
WEIGHTS_DIR = "/weights"
REPO_DIR = "/root/yarngpt"  # the repo root *is* the `yarngpt` package
WAV_CFG = f"{WEIGHTS_DIR}/wavtokenizer_mediumdata_frame75_3s_nq1_code4096_dim512_kmeans200_attn.yaml"

# Read at deploy time on your laptop.
GPU = os.environ.get("YARNGPT_GPU", "L4")  # "T4" is cheaper and slower; A100/H100 is wasted on a 360M model
MIN_CONTAINERS = int(os.environ.get("YARNGPT_MIN_CONTAINERS", "0"))  # 1 = always warm (billed all the time)
LOCAL_BEAMS = 2  # Yoruba/Igbo/Hausa: the author used 5 (best quality, ~5x slower); 1 is fastest


WAV_REPO = "novateur/WavTokenizer-large-speech-75token"
WAV_CKPT_NAME = "wavtokenizer_large_speech_320_24k.ckpt"


def download_weights():
    """Runs once at image build time so cold starts don't re-download anything.

    10 Nov 2026: a rebuild failed with 404 for WAV_CKPT_NAME (the file was renamed or moved in
    the Hugging Face repo). So every checkpoint in the repo is downloaded and the right one is
    found by name at start-up (find_wav_ckpt); the names are printed in the build log.
    """
    import glob

    from huggingface_hub import hf_hub_download, snapshot_download

    snapshot_download(MODEL_ID)
    hf_hub_download(
        "novateur/WavTokenizer-medium-speech-75token",
        "wavtokenizer_mediumdata_frame75_3s_nq1_code4096_dim512_kmeans200_attn.yaml",
        local_dir=WEIGHTS_DIR,
    )
    snapshot_download(WAV_REPO, local_dir=f"{WEIGHTS_DIR}/wav", allow_patterns=["*.ckpt", "*.pt", "*.bin", "*.safetensors"])
    found = sorted(glob.glob(f"{WEIGHTS_DIR}/wav/**/*", recursive=True))
    print("[yarngpt] WavTokenizer files:", [f for f in found if not f.endswith("/")])
    if not any(f.endswith((".ckpt", ".pt", ".bin", ".safetensors")) for f in found):
        raise RuntimeError(f"no checkpoint found in {WAV_REPO}; open the repo on Hugging Face and check its files")


def find_wav_ckpt() -> str:
    """The WavTokenizer checkpoint: the known name if present, else the best match by name."""
    import glob

    files = [f for f in glob.glob(f"{WEIGHTS_DIR}/wav/**/*", recursive=True) if f.endswith((".ckpt", ".pt", ".bin", ".safetensors"))]
    exact = [f for f in files if f.endswith(WAV_CKPT_NAME)]
    if exact:
        return exact[0]
    ranked = sorted(files, key=lambda f: (("24k" in f) + ("320" in f) + ("large" in f) + f.endswith(".ckpt")), reverse=True)
    if not ranked:
        raise FileNotFoundError(f"no WavTokenizer checkpoint under {WEIGHTS_DIR}/wav")
    return ranked[0]

image = (
    modal.Image.debian_slim(python_version="3.11")
    # build tools for `pesq`, portaudio for `sounddevice` (both pulled in by outetts)
    .apt_install("git", "ffmpeg", "build-essential", "portaudio19-dev", "libsndfile1")
    .pip_install(
        "torch==2.5.1",
        "torchaudio==2.5.1",
        "numpy<2",
        "transformers==4.47.1",  # versions pinned by the YarnGPT repo
        "outetts==0.2.3",
        "uroman",
        "inflect",
        "huggingface_hub[hf_transfer]",
        "fastapi[standard]",
    )
    .env({"HF_HUB_ENABLE_HF_TRANSFER": "1"})
    .run_commands(f"git clone --depth 1 https://github.com/saheedniyi02/yarngpt.git {REPO_DIR}")
    .run_function(download_weights)
)

app = modal.App("yarngpt", image=image)

ENGLISH_SPEAKERS = ["idera", "chinenye", "jude", "emma", "umar", "joke", "zainab",
                    "osagie", "remi", "tayo", "onye", "regina", "saheed"]
LOCAL_SPEAKERS = {
    "yoruba": ["yoruba_male2", "yoruba_female2", "yoruba_female1"],
    "igbo": ["igbo_female2", "igbo_male2", "igbo_female1"],
    "hausa": ["hausa_female1", "hausa_female2", "hausa_male2", "hausa_male1"],
}
DEFAULT_LOCAL = {"yoruba": "yoruba_female2", "igbo": "igbo_female2", "hausa": "hausa_female1"}


def split_text(text: str, max_chars: int = 250) -> list[str]:
    """YarnGPT handles ~30-40 s of audio per pass, so long text is split by sentence."""
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    chunks, cur = [], ""
    for s in sentences:
        if len(cur) + len(s) + 1 <= max_chars:
            cur = f"{cur} {s}".strip()
        else:
            if cur:
                chunks.append(cur)
            cur = s
    if cur:
        chunks.append(cur)
    return chunks or [text]


@app.cls(
    gpu=GPU,
    scaledown_window=120,   # shut down after 2 idle minutes so you don't burn credits
    min_containers=MIN_CONTAINERS,
    timeout=600,
)
class YarnGPT:
    @modal.enter()
    def load(self):
        import torch
        from transformers import AutoModelForCausalLM

        sys.path.insert(0, "/root")
        from yarngpt.audiotokenizer import AudioTokenizerV2

        self.torch = torch
        wav_ckpt = find_wav_ckpt()
        print(f"[yarngpt] WavTokenizer checkpoint: {wav_ckpt}")
        self.tok = AudioTokenizerV2(MODEL_ID, wav_ckpt, WAV_CFG)
        # float16: fast on every NVIDIA GPU. If the audio ever sounds garbled, try torch.float32.
        self.model = AutoModelForCausalLM.from_pretrained(MODEL_ID, torch_dtype=torch.float16).to(self.tok.device)
        self.model.eval()
        print(f"[yarngpt] model on {self.tok.device}, gpu={GPU}, dtype={self.model.dtype}")
        # Warm-up: the first generation pays one-off CUDA start-up costs; do it before any request.
        t0 = time.perf_counter()
        try:
            self._generate_chunk("Avenza is ready.", "english", "idera")
            print(f"[yarngpt] warm-up {time.perf_counter() - t0:.1f}s")
        except Exception as exc:  # noqa: BLE001 - a failed warm-up must not stop the container
            print(f"[yarngpt] warm-up failed: {exc}")

    def _generate_chunk(self, text: str, lang: str, speaker: str | None):
        prompt = self.tok.create_prompt(text, lang=lang, speaker_name=speaker)
        input_ids = self.tok.tokenize_prompt(prompt)
        gen_kwargs = dict(temperature=0.1, repetition_penalty=1.1, max_length=4000)
        if lang != "english" and LOCAL_BEAMS > 1:
            gen_kwargs["num_beams"] = LOCAL_BEAMS
        with self.torch.inference_mode():
            output = self.model.generate(input_ids=input_ids, **gen_kwargs)
        self._last_tokens = int(output.shape[-1] - input_ids.shape[-1])
        codes = self.tok.get_codes(output)
        return self.tok.get_audio(codes)  # tensor [1, samples] @ 24 kHz

    @modal.method()
    def synthesize(self, text: str, lang: str = "english", speaker: str | None = "idera") -> bytes:
        import torchaudio

        lang = lang.lower()
        if lang not in ("english", "yoruba", "igbo", "hausa"):
            raise ValueError("lang must be english, yoruba, igbo or hausa")
        if lang != "english" and (not speaker or speaker in ENGLISH_SPEAKERS):
            speaker = DEFAULT_LOCAL[lang]  # an English voice with a local language: use a matching local voice

        t0 = time.perf_counter()
        tokens = 0
        pieces = []
        for chunk in split_text(text):
            pieces.append(self._generate_chunk(chunk, lang, speaker))
            tokens += self._last_tokens
        audio = self.torch.cat(pieces, dim=-1)
        dt = time.perf_counter() - t0
        print(f"[yarngpt] {lang}/{speaker}: {len(text)} chars, {audio.shape[-1] / 24000:.1f}s audio "
              f"in {dt:.1f}s ({tokens} tokens, {tokens / max(dt, 1e-6):.0f} tok/s)")

        buf = io.BytesIO()
        torchaudio.save(buf, audio.float().cpu(), sample_rate=24000, format="wav")
        return buf.getvalue()

    @modal.fastapi_endpoint(method="POST", docs=True)
    def tts(self, body: dict):
        from fastapi import HTTPException
        from fastapi.responses import Response

        text = (body.get("text") or "").strip()
        if not text:
            raise HTTPException(400, "`text` is required")
        if len(text) > 3000:
            raise HTTPException(400, "text too long (max 3000 chars)")
        try:
            wav = self.synthesize.local(
                text, body.get("lang", "english"), body.get("speaker", "idera")
            )
        except (ValueError, FileNotFoundError) as e:
            raise HTTPException(400, str(e))
        return Response(content=wav, media_type="audio/wav")

    @modal.fastapi_endpoint(method="GET")
    def speakers(self):
        return {"english": ENGLISH_SPEAKERS, **LOCAL_SPEAKERS}


@app.local_entrypoint()
def main(text: str = "Wetin dey happen? This na YarnGPT running on Modal.",
         lang: str = "english", speaker: str = "idera", out: str = "yarngpt_out.wav"):
    wav = YarnGPT().synthesize.remote(text, lang, speaker)
    with open(out, "wb") as f:
        f.write(wav)
    print(f"Saved {out} ({len(wav) / 1024:.0f} KB)")
