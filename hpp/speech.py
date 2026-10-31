"""朗读：Windows SAPI（System.Speech）封装，嗓音列表带缓存。"""
from __future__ import annotations

import base64
import platform
import subprocess
import sys
import threading

# --------------------------------------------------------------------------
# 朗读
# --------------------------------------------------------------------------
_VOICE_CACHE = None
_VOICE_LOCK = threading.Lock()


def list_sapi_voices() -> list:
    """列出系统已安装的 SAPI 嗓音：[(名称, 性别, 语言)]。

    只在 Windows 有效，首次调用约 0.5~1 s，之后走缓存。失败一律返回空列表。
    """
    global _VOICE_CACHE
    with _VOICE_LOCK:
        if _VOICE_CACHE is not None:
            return _VOICE_CACHE
        voices = []
        if platform.system() == "Windows":
            script = (
                "Add-Type -AssemblyName System.Speech;"
                "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer;"
                "$s.GetInstalledVoices() | ForEach-Object { "
                "$_.VoiceInfo.Name + '|' + $_.VoiceInfo.Gender + '|' + $_.VoiceInfo.Culture.Name }"
            )
            for shell in ("powershell", "pwsh"):
                try:
                    out = subprocess.run(
                        [shell, "-NoProfile", "-NoLogo", "-Command", script],
                        capture_output=True, text=True, encoding="utf-8",
                        errors="replace", timeout=30,
                        creationflags=0x08000000,
                    )
                    if out.returncode == 0 and out.stdout.strip():
                        for line in out.stdout.strip().splitlines():
                            parts = [p.strip() for p in line.split("|")]
                            if len(parts) >= 3 and parts[0]:
                                voices.append((parts[0], parts[1], parts[2]))
                        break
                except Exception:
                    continue
        _VOICE_CACHE = voices
        return voices


def resolve_voice(pref: str) -> str:
    """把设置里的嗓音偏好解析成具体 VoiceId；空字符串表示交给系统默认。"""
    pref = (pref or "auto").strip()
    if not pref or pref == "auto":
        return ""
    voices = list_sapi_voices()
    if not voices:
        return ""
    if pref in ("female", "male"):
        want = pref
        cands = [v for v in voices if (v[1] or "").lower() == want]
        # 中文嗓音优先，否则随便挑一个
        zh = [v for v in cands if "zh" in (v[2] or "").lower()]
        pick = zh or cands
        return pick[0][0] if pick else ""
    names = [v[0] for v in voices]
    return pref if pref in names else ""


class Speech:
    """优先用 Windows 自带的 System.Speech（常驻进程，延迟低）；其他平台走系统命令。"""

    def __init__(self, rate: int = 0, voice: str = "auto"):
        self.rate = max(-10, min(10, int(rate)))
        self.voice = voice or "auto"
        self.system = platform.system()
        self._proc = None
        self._lock = threading.Lock()
        self._shell = None

    def set_rate(self, rate: int) -> None:
        rate = max(-10, min(10, int(rate)))
        if rate != self.rate:
            self.rate = rate
            self.close()  # 下次说话时按新语速重建

    def set_voice(self, voice: str) -> None:
        voice = voice or "auto"
        if voice != self.voice:
            self.voice = voice
            self.close()  # 下次说话时按新嗓音重建

    def _shell_candidates(self):
        return [self._shell] if self._shell else ["powershell", "pwsh"]

    def _ensure_windows(self) -> bool:
        if self._proc is not None and self._proc.poll() is None:
            return True
        picked = resolve_voice(self.voice)
        select = ""
        if picked:
            safe = picked.replace("'", "''")
            select = f"try {{ $s.SelectVoice('{safe}') }} catch {{}};"
        script = (
            "Add-Type -AssemblyName System.Speech;"
            "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer;"
            f"$s.Rate = {self.rate};"
            + select +
            "while ($true) {"
            "  $l = [Console]::In.ReadLine();"
            "  if ($null -eq $l) { break }"
            "  if ($l -eq '##quit##') { break }"
            "  if ($l.Trim().Length -eq 0) { continue }"
            "  $t = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($l));"
            "  if ($t.Trim().Length -gt 0) { $s.Speak($t) }"
            "}"
        )
        flags = 0x08000000 if self.system == "Windows" else 0
        for shell in self._shell_candidates():
            try:
                self._proc = subprocess.Popen(
                    [shell, "-NoProfile", "-NoLogo", "-Command", script],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    text=True,
                    encoding="ascii",
                    errors="ignore",
                    creationflags=flags,
                )
                self._shell = shell
                return True
            except Exception:
                self._proc = None
        print("[warn] 找不到可用的 PowerShell，朗读不可用", file=sys.stderr)
        return False

    def speak(self, text: str) -> None:
        text = text.strip()
        if not text:
            return
        threading.Thread(target=self._speak_worker, args=(text,), daemon=True).start()

    def _speak_worker(self, text: str) -> None:
        with self._lock:
            if self.system == "Windows":
                if self._ensure_windows() and self._proc and self._proc.stdin:
                    try:
                        payload = base64.b64encode(text.encode("utf-8")).decode("ascii")
                        self._proc.stdin.write(payload + "\n")
                        self._proc.stdin.flush()
                        return
                    except Exception:
                        self._proc = None
                try:
                    picked = resolve_voice(self.voice)
                    select = ""
                    if picked:
                        select = f"try {{ $s.SelectVoice('{picked.replace(chr(39), chr(39) * 2)}') }} catch {{}};"
                    ps = (
                        "Add-Type -AssemblyName System.Speech;"
                        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer;"
                        f"$s.Rate = {self.rate};"
                        + select +
                        "$s.Speak([Text.Encoding]::UTF8.GetString("
                        f"[Convert]::FromBase64String('{base64.b64encode(text.encode()).decode()}')))"
                    )
                    subprocess.run(
                        [self._shell or "powershell", "-NoProfile", "-Command", ps],
                        creationflags=0x08000000,
                        timeout=30,
                    )
                    return
                except Exception:
                    pass
            elif self.system == "Darwin":
                try:
                    cmd = ["say"]
                    picked = resolve_voice(self.voice)
                    if picked:
                        cmd += ["-v", picked]
                    subprocess.run(cmd + [text], timeout=30)
                    return
                except Exception:
                    pass
            else:
                for cmd in ("spd-say", "espeak-ng", "espeak"):
                    try:
                        subprocess.run([cmd, text], timeout=30)
                        return
                    except Exception:
                        continue

    def close(self) -> None:
        proc = self._proc
        self._proc = None
        if proc and proc.poll() is None:
            try:
                if proc.stdin:
                    proc.stdin.write("##quit##\n")
                    proc.stdin.flush()
                proc.wait(timeout=2)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
