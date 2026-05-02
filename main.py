import asyncio
import base64
import io
import json
import mimetypes
import re
import struct
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import unquote, urlparse

import aiofiles
import aiohttp
from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, StarTools
from astrbot.core import AstrBotConfig
from astrbot.core.message import components as Comp

try:
    from PIL import Image as PILImage
except Exception:  # pragma: no cover - optional dependency at runtime
    PILImage = None


class GPTImage2Plugin(Star):
    DEFAULT_TEXT_RATIO = "3:4"
    DEFAULT_EDIT_PROMPT = "请保持主体和主要元素，生成高质量重绘图像。"
    DEFAULT_MODEL = "gpt-image-2"
    DEFAULT_ROUTE_MODE = "auto"
    DEFAULT_TIMEOUT = 240
    DEFAULT_DENY_MESSAGE = "❌ 当前未在白名单内"
    MAX_PROMPT_LENGTH = 4000

    PRESETS: Dict[str, Dict[str, str]] = {
        "1:1": {
            "size": "2880x2880",
            "alias": "gpt-image-2-2880x2880(1:1)",
        },
        "3:2": {
            "size": "3456x2304",
            "alias": "gpt-image-2-3456x2304(3:2)",
        },
        "2:3": {
            "size": "2304x3456",
            "alias": "gpt-image-2-2304x3456(2:3)",
        },
        "4:3": {
            "size": "3264x2448",
            "alias": "gpt-image-2-3264x2448(4:3)",
        },
        "3:4": {
            "size": "2448x3264",
            "alias": "gpt-image-2-2448x3264(3:4)",
        },
        "16:9": {
            "size": "3840x2160",
            "alias": "gpt-image-2-3840x2160(16:9)",
        },
        "9:16": {
            "size": "2160x3840",
            "alias": "gpt-image-2-2160x3840(9:16)",
        },
        "21:9": {
            "size": "3808x1632",
            "alias": "gpt-image-2-3808x1632(21:9)",
        },
        "9:21": {
            "size": "1632x3808",
            "alias": "gpt-image-2-1632x3808(9:21)",
        },
    }

    FREE_PRESETS: Dict[str, Dict[str, str]] = {
        "1:1": {
            "size": "1248x1248",
            "alias": "gpt-image-2-1248x1248(1:1)",
        },
        "3:2": {
            "size": "1536x1024",
            "alias": "gpt-image-2-1536x1024(3:2)",
        },
        "2:3": {
            "size": "1024x1536",
            "alias": "gpt-image-2-1024x1536(2:3)",
        },
        "4:3": {
            "size": "1440x1072",
            "alias": "gpt-image-2-1440x1072(4:3)",
        },
        "3:4": {
            "size": "1072x1440",
            "alias": "gpt-image-2-1072x1440(3:4)",
        },
        "16:9": {
            "size": "1664x928",
            "alias": "gpt-image-2-1664x928(16:9)",
        },
        "9:16": {
            "size": "928x1664",
            "alias": "gpt-image-2-928x1664(9:16)",
        },
        "21:9": {
            "size": "1904x816",
            "alias": "gpt-image-2-1904x816(21:9)",
        },
        "9:21": {
            "size": "816x1904",
            "alias": "gpt-image-2-816x1904(9:21)",
        },
    }

    RATIO_ALIASES: Dict[str, str] = {
        "1:1": "1:1",
        "1比1": "1:1",
        "一比一": "1:1",
        "3:2": "3:2",
        "3比2": "3:2",
        "三比二": "3:2",
        "2:3": "2:3",
        "2比3": "2:3",
        "二比三": "2:3",
        "4:3": "4:3",
        "4比3": "4:3",
        "四比三": "4:3",
        "3:4": "3:4",
        "3比4": "3:4",
        "三比四": "3:4",
        "16:9": "16:9",
        "16比9": "16:9",
        "十六比九": "16:9",
        "9:16": "9:16",
        "9比16": "9:16",
        "九比十六": "9:16",
        "21:9": "21:9",
        "21比9": "21:9",
        "二十一比九": "21:9",
        "9:21": "9:21",
        "9比21": "9:21",
        "九比二十一": "9:21",
    }

    ROUTE_MODES = ("auto", "responses", "chat_completions", "images")

    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.conf = config
        self._session: Optional[aiohttp.ClientSession] = None
        self._session_lock = asyncio.Lock()
        self.plugin_data_dir = StarTools.get_data_dir("astrbot_plugin_gptimage2")
        self.temp_dir = Path(self.plugin_data_dir) / "temp"
        self.image_dir = Path(self.plugin_data_dir) / "images"
        self.temp_dir.mkdir(exist_ok=True, parents=True)
        self.image_dir.mkdir(exist_ok=True, parents=True)

    async def initialize(self):
        async with self._session_lock:
            if not self._session or self._session.closed:
                self._session = aiohttp.ClientSession()
        logger.info("gptimage2生图插件初始化完成")

    async def terminate(self):
        async with self._session_lock:
            if self._session and not self._session.closed:
                await self._session.close()
            self._session = None
        logger.info("gptimage2生图插件已终止")

    @filter.command("gptimage2", prefix_optional=True)
    async def on_gptimage2(self, event: AstrMessageEvent):
        sender_id = self._sender_id(event)
        if not self._is_whitelisted_user(sender_id):
            logger.info(f"[gptimage2] deny non-whitelist sender: {sender_id or 'unknown'}")
            yield event.plain_result(self._deny_message())
            return

        api_key = str(self.conf.get("api_key", "")).strip()
        if not api_key:
            yield event.plain_result("❌ 请先在插件配置里填写 API Key")
            return

        raw_input = event.message_str.strip()
        command_name = "gptimage2"
        if raw_input.startswith(command_name):
            user_input = raw_input[len(command_name):].strip()
        else:
            user_input = raw_input

        image_bytes = await self._get_image_from_event(event)
        prompt_text, preset, invalid_size = self._parse_request(user_input)

        if invalid_size:
            yield event.plain_result(f"❌ 当前未收录尺寸 {invalid_size}，请改用 1:1 / 3:2 / 2:3 / 4:3 / 3:4 / 16:9 / 9:16 / 21:9 / 9:21")
            return

        if not prompt_text and image_bytes:
            prompt_text = self.DEFAULT_EDIT_PROMPT

        if not prompt_text:
            yield event.plain_result("❌ 请输入提示词，例如：/gptimage2 21:9 生成一个赛博朋克城市海报")
            return

        if len(prompt_text) > self.MAX_PROMPT_LENGTH:
            yield event.plain_result(f"❌ 提示词过长，最大支持 {self.MAX_PROMPT_LENGTH} 字符")
            return

        if preset is None:
            if image_bytes:
                resolution = self._get_image_resolution(image_bytes)
                if resolution:
                    preset = self._closest_preset_for_resolution(*resolution)
            if preset is None:
                preset = self._default_preset()

        model_name = preset["alias"] or self._default_model()
        route_candidates = self._resolve_route_candidates()
        mode_label = "图生图" if image_bytes else "文生图"

        yield event.plain_result(f"🎨 正在进行 {mode_label} · {preset['size']} · {route_candidates[0]}")

        image_result, used_route, error = await self._generate_image(
            prompt=prompt_text,
            image_bytes=image_bytes,
            model_name=model_name,
            size=preset["size"],
            routes=route_candidates,
        )
        if error:
            yield event.plain_result(f"❌ 生成失败: {error}")
            return
        if not image_result:
            yield event.plain_result("❌ 未获取到图片结果")
            return

        source_url, image_payload = image_result
        async for result in self._save_and_send_image(event, source_url or "", image_payload):
            yield result
        yield event.plain_result(f"✅ 已完成 · 路由 {used_route} · 模型 {model_name}")

    def _default_model(self) -> str:
        return str(self.conf.get("default_model", self.DEFAULT_MODEL)).strip() or self.DEFAULT_MODEL

    def _use_free_only_resolutions(self) -> bool:
        value = self.conf.get("free_only_resolutions", True)
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        return str(value).strip().lower() not in {"0", "false", "no", "off", "disabled"}

    def _presets(self) -> Dict[str, Dict[str, str]]:
        return self.FREE_PRESETS if self._use_free_only_resolutions() else self.PRESETS

    def _default_preset(self) -> Dict[str, str]:
        presets = self._presets()
        raw = str(self.conf.get("default_resolution", self.DEFAULT_TEXT_RATIO)).strip()
        if raw:
            normalized_size = re.sub(r"\s+", "", raw.lower())
            preset = self._preset_from_size(normalized_size)
            if preset is not None:
                return preset
            normalized_ratio = self.RATIO_ALIASES.get(raw, raw)
            if normalized_ratio in presets:
                return presets[normalized_ratio]
        return presets[self.DEFAULT_TEXT_RATIO]

    def _normalized_quality(self) -> str:
        quality = str(self.conf.get("quality", "high")).strip().lower()
        if quality == "high":
            return "high"
        return ""

    def _normalized_background(self) -> str:
        background = str(self.conf.get("background", "auto")).strip().lower()
        if background in {"transparent", "white"}:
            return background
        return ""

    def _timeout(self) -> int:
        try:
            return max(30, int(self.conf.get("timeout_seconds", self.DEFAULT_TIMEOUT)))
        except Exception:
            return self.DEFAULT_TIMEOUT

    def _save_images(self) -> bool:
        try:
            return bool(self.conf.get("save_images", False))
        except Exception:
            return False

    def _route_mode(self) -> str:
        mode = str(self.conf.get("route_mode", self.DEFAULT_ROUTE_MODE)).strip().lower()
        if mode in self.ROUTE_MODES:
            return mode
        return self.DEFAULT_ROUTE_MODE

    def _deny_message(self) -> str:
        return str(self.conf.get("deny_message", self.DEFAULT_DENY_MESSAGE)).strip() or self.DEFAULT_DENY_MESSAGE

    def _sender_id(self, event: AstrMessageEvent) -> str:
        try:
            sender_id = event.get_sender_id()
        except Exception:
            sender_id = None
        if sender_id is None:
            return ""
        return str(sender_id).strip()

    def _user_whitelist(self) -> List[str]:
        raw_value = self.conf.get("user_whitelist", "")
        if isinstance(raw_value, (list, tuple, set)):
            values = [str(item).strip() for item in raw_value if str(item).strip()]
            return list(dict.fromkeys(values))

        text = str(raw_value or "").strip()
        if not text:
            return []

        if text.startswith("[") and text.endswith("]"):
            try:
                parsed = json.loads(text)
            except Exception:
                parsed = None
            if isinstance(parsed, list):
                values = [str(item).strip() for item in parsed if str(item).strip()]
                return list(dict.fromkeys(values))

        values = [item.strip() for item in re.split(r"[\s,，;；|]+", text) if item.strip()]
        return list(dict.fromkeys(values))

    def _is_whitelisted_user(self, sender_id: str) -> bool:
        whitelist = self._user_whitelist()
        if not whitelist:
            return True
        if not sender_id:
            return False
        return sender_id in whitelist

    def _resolve_route_candidates(self) -> List[str]:
        mode = self._route_mode()
        if mode == "auto":
            return ["responses", "chat_completions", "images"]
        return [mode]

    @staticmethod
    def _segment_type_name(seg: Any) -> str:
        if not seg:
            return ""
        return seg.__class__.__name__.lower()

    def _is_segment_type(self, seg: Any, type_name: str) -> bool:
        cls = getattr(Comp, type_name, None)
        if cls is not None:
            try:
                if isinstance(seg, cls):
                    return True
            except Exception:
                pass
        return self._segment_type_name(seg) == type_name.lower()

    @staticmethod
    def _extract_segment_sources(seg: Any) -> List[str]:
        sources: List[str] = []
        for key in ("file", "url", "path", "src"):
            value = getattr(seg, key, None)
            if isinstance(value, str) and value.strip():
                sources.append(value.strip())
        return list(dict.fromkeys(sources))

    def _iter_event_segments(self, event: AstrMessageEvent) -> List[Any]:
        message_list = getattr(getattr(event, "message_obj", None), "message", None)
        if not message_list:
            try:
                message_list = event.get_messages()
            except Exception:
                message_list = []
        segments: List[Any] = []
        for seg in message_list or []:
            if self._is_segment_type(seg, "Reply") and getattr(seg, "chain", None):
                segments.extend(list(seg.chain))
            else:
                segments.append(seg)
        return segments

    async def _ensure_session(self) -> aiohttp.ClientSession:
        async with self._session_lock:
            if not self._session or self._session.closed:
                self._session = aiohttp.ClientSession()
            return self._session

    async def _download_bytes(self, url: str, include_auth: bool = False) -> Optional[bytes]:
        session = await self._ensure_session()
        headers: Dict[str, str] = {}
        if include_auth:
            headers["Authorization"] = f"Bearer {self.conf.get('api_key', '')}"
        try:
            async with session.get(
                url,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=min(self._timeout(), 120)),
            ) as resp:
                if resp.status != 200:
                    logger.warning(f"下载图片失败: status={resp.status}, url={url[:180]}")
                    return None
                return await resp.read()
        except Exception as exc:
            logger.warning(f"下载图片失败: {exc}")
            return None

    async def _load_bytes(self, src: str) -> Optional[bytes]:
        if not src:
            return None
        if src.startswith("data:") and "," in src:
            try:
                return base64.b64decode(src.split(",", 1)[1])
            except Exception:
                return None
        if src.startswith("base64://"):
            try:
                return base64.b64decode(src[9:])
            except Exception:
                return None
        if src.startswith("http://") or src.startswith("https://"):
            return await self._download_bytes(src, include_auth=False)
        path = Path(src)
        if path.is_file():
            try:
                async with aiofiles.open(path, "rb") as handle:
                    return await handle.read()
            except Exception:
                return None
        return None

    async def _load_segment_payload(self, seg: Any) -> Optional[bytes]:
        direct_data = getattr(seg, "data", None)
        if isinstance(direct_data, (bytes, bytearray)) and direct_data:
            return bytes(direct_data)
        for src in self._extract_segment_sources(seg):
            payload = await self._load_bytes(src)
            if payload:
                return payload
        return None

    async def _get_image_from_event(self, event: AstrMessageEvent) -> Optional[bytes]:
        for seg in self._iter_event_segments(event):
            if not self._is_segment_type(seg, "Image"):
                continue
            payload = await self._load_segment_payload(seg)
            if payload:
                return payload
        return None

    @staticmethod
    def _detect_mime_type(data: bytes) -> str:
        if data.startswith(b"\x89PNG\r\n\x1a\n"):
            return "image/png"
        if data.startswith(b"\xff\xd8\xff"):
            return "image/jpeg"
        if data.startswith((b"GIF87a", b"GIF89a")):
            return "image/gif"
        if data.startswith(b"RIFF") and len(data) > 12 and data[8:12] == b"WEBP":
            return "image/webp"
        if data.startswith(b"BM"):
            return "image/bmp"
        return "image/png"

    @classmethod
    def _data_url(cls, data: bytes) -> str:
        return f"data:{cls._detect_mime_type(data)};base64,{base64.b64encode(data).decode('utf-8')}"

    def _parse_request(self, text: str) -> Tuple[str, Optional[Dict[str, str]], Optional[str]]:
        cleaned = text.strip()
        preset: Optional[Dict[str, str]] = None
        invalid_size: Optional[str] = None

        size_match = re.search(r"\b(\d{3,4})\s*[xX]\s*(\d{3,4})\b", cleaned)
        if size_match:
            normalized_size = f"{int(size_match.group(1))}x{int(size_match.group(2))}"
            preset = self._preset_from_size(normalized_size)
            if preset is None:
                invalid_size = normalized_size
            cleaned = (cleaned[: size_match.start()] + " " + cleaned[size_match.end() :]).strip()

        if preset is None:
            ratio_match = self._find_ratio_match(cleaned)
            if ratio_match:
                preset = self._presets()[ratio_match[1]]
                cleaned = (cleaned[: ratio_match[0].start()] + " " + cleaned[ratio_match[0].end() :]).strip()

        cleaned = re.sub(r"^(生成(?:一个|一张)?|画(?:一个|一张)?|来(?:一张|个)?)(\s+|$)", "", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip(" ，,")
        return cleaned, preset, invalid_size

    def _find_ratio_match(self, text: str) -> Optional[Tuple[re.Match[str], str]]:
        for raw, normalized in sorted(self.RATIO_ALIASES.items(), key=lambda item: len(item[0]), reverse=True):
            pattern = re.compile(re.escape(raw), re.IGNORECASE)
            match = pattern.search(text)
            if match:
                return match, normalized
        return None

    def _preset_from_size(self, size: str) -> Optional[Dict[str, str]]:
        for preset in self._presets().values():
            if preset["size"] == size:
                return preset
        return None

    def _get_image_resolution(self, image_bytes: bytes) -> Optional[Tuple[int, int]]:
        if PILImage is not None:
            try:
                with PILImage.open(io.BytesIO(image_bytes)) as image:
                    width, height = image.size
                if width > 0 and height > 0:
                    return width, height
            except Exception:
                pass

        if image_bytes.startswith(b"\x89PNG\r\n\x1a\n") and len(image_bytes) >= 24:
            width, height = struct.unpack(">II", image_bytes[16:24])
            if width > 0 and height > 0:
                return width, height

        if image_bytes[:2] == b"\xff\xd8":
            index = 2
            while index + 9 < len(image_bytes):
                if image_bytes[index] != 0xFF:
                    index += 1
                    continue
                marker = image_bytes[index + 1]
                if marker in {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}:
                    height, width = struct.unpack(">HH", image_bytes[index + 5 : index + 9])
                    if width > 0 and height > 0:
                        return width, height
                    break
                if marker in {0xD8, 0xD9}:
                    index += 2
                    continue
                segment_length = struct.unpack(">H", image_bytes[index + 2 : index + 4])[0]
                index += 2 + segment_length
        return None

    def _closest_preset_for_resolution(self, width: int, height: int) -> Optional[Dict[str, str]]:
        if width <= 0 or height <= 0:
            return None

        target_ratio = width / height
        target_area = width * height
        best_key: Optional[str] = None
        best_score: Optional[Tuple[float, float, float]] = None

        presets = self._presets()
        for key, preset in presets.items():
            preset_width, preset_height = map(int, preset["size"].split("x", 1))
            score = (
                abs((preset_width / preset_height) - target_ratio),
                abs((preset_width * preset_height) - target_area) / max(target_area, 1),
                abs(preset_width - width) / max(width, 1) + abs(preset_height - height) / max(height, 1),
            )
            if best_score is None or score < best_score:
                best_score = score
                best_key = key

        if best_key is None:
            return None
        return presets[best_key]

    def _normalize_base_url(self) -> str:
        url = str(self.conf.get("base_url", "https://fps.de5.net")).strip().rstrip("/")
        if not url:
            url = "https://fps.de5.net"
        for suffix in (
            "/v1/chat/completions",
            "/v1/responses",
            "/v1/images/generations",
            "/v1/images/edits",
            "/chat/completions",
            "/responses",
            "/images/generations",
            "/images/edits",
            "/v1",
        ):
            if url.endswith(suffix):
                url = url[: -len(suffix)]
                break
        return url.rstrip("/")

    def _auth_headers(self, json_request: bool = True) -> Dict[str, str]:
        headers = {"Authorization": f"Bearer {str(self.conf.get('api_key', '')).strip()}"}
        if json_request:
            headers["Content-Type"] = "application/json"
        return headers

    async def _generate_image(
        self,
        prompt: str,
        image_bytes: Optional[bytes],
        model_name: str,
        size: str,
        routes: List[str],
    ) -> Tuple[Optional[Tuple[Optional[str], bytes]], Optional[str], Optional[str]]:
        last_error = "未知错误"
        for route in routes:
            try:
                if route == "images":
                    payload = await self._call_images_route(prompt, image_bytes, model_name, size)
                elif route == "responses":
                    payload = await self._call_responses_route(prompt, image_bytes, model_name, size)
                elif route == "chat_completions":
                    payload = await self._call_chat_route(prompt, image_bytes, model_name, size)
                else:
                    continue

                image = await self._extract_first_image(payload)
                if image is None:
                    last_error = f"{route} 没有返回图片"
                    continue
                return image, route, None
            except Exception as exc:
                last_error = self._translate_error(str(exc))
                logger.warning(f"[gptimage2] route={route} failed: {exc}")
        return None, None, last_error

    async def _call_images_route(
        self,
        prompt: str,
        image_bytes: Optional[bytes],
        model_name: str,
        size: str,
    ) -> Dict[str, Any]:
        session = await self._ensure_session()
        base_url = self._normalize_base_url()
        timeout = aiohttp.ClientTimeout(total=self._timeout())
        quality = self._normalized_quality()
        background = self._normalized_background()

        if image_bytes is None:
            body: Dict[str, Any] = {
                "model": model_name,
                "prompt": prompt,
                "n": 1,
                "size": size,
                "response_format": "b64_json",
            }
            if quality:
                body["quality"] = quality
            if background:
                body["background"] = background
            async with session.post(
                f"{base_url}/v1/images/generations",
                headers=self._auth_headers(json_request=True),
                json=body,
                timeout=timeout,
            ) as resp:
                return await self._read_json_response(resp)

        form = aiohttp.FormData()
        form.add_field("model", model_name)
        form.add_field("prompt", prompt)
        form.add_field("size", size)
        form.add_field("response_format", "b64_json")
        if quality:
            form.add_field("quality", quality)
        if background:
            form.add_field("background", background)
        form.add_field(
            "image",
            image_bytes,
            filename=f"source.{self._extension_for_mime(self._detect_mime_type(image_bytes))}",
            content_type=self._detect_mime_type(image_bytes),
        )
        async with session.post(
            f"{base_url}/v1/images/edits",
            headers=self._auth_headers(json_request=False),
            data=form,
            timeout=timeout,
        ) as resp:
            return await self._read_json_response(resp)

    async def _call_responses_route(
        self,
        prompt: str,
        image_bytes: Optional[bytes],
        model_name: str,
        size: str,
    ) -> Dict[str, Any]:
        session = await self._ensure_session()
        base_url = self._normalize_base_url()
        timeout = aiohttp.ClientTimeout(total=self._timeout())
        quality = self._normalized_quality()
        background = self._normalized_background()

        content: List[Dict[str, Any]] = [{"type": "input_text", "text": prompt}]
        action = "generate"
        if image_bytes is not None:
            content.append({"type": "input_image", "image_url": self._data_url(image_bytes)})
            action = "edit"

        tool: Dict[str, Any] = {
            "type": "image_generation",
            "action": action,
            "model": model_name,
            "size": size,
        }
        if quality:
            tool["quality"] = quality
        if background:
            tool["background"] = background

        body: Dict[str, Any] = {
            "model": model_name,
            "input": [{"role": "user", "content": content}],
            "tools": [tool],
            "tool_choice": {"type": "image_generation"},
            "stream": False,
            "n": 1,
            "size": size,
        }
        if quality:
            body["quality"] = quality
        if background:
            body["background"] = background

        async with session.post(
            f"{base_url}/v1/responses",
            headers=self._auth_headers(json_request=True),
            json=body,
            timeout=timeout,
        ) as resp:
            return await self._read_json_response(resp)

    async def _call_chat_route(
        self,
        prompt: str,
        image_bytes: Optional[bytes],
        model_name: str,
        size: str,
    ) -> Dict[str, Any]:
        session = await self._ensure_session()
        base_url = self._normalize_base_url()
        timeout = aiohttp.ClientTimeout(total=self._timeout())
        quality = self._normalized_quality()
        background = self._normalized_background()

        content: List[Dict[str, Any]] = [{"type": "text", "text": prompt}]
        if image_bytes is not None:
            content.append({"type": "image_url", "image_url": {"url": self._data_url(image_bytes)}})

        body: Dict[str, Any] = {
            "model": model_name,
            "messages": [{"role": "user", "content": content}],
            "stream": False,
            "n": 1,
            "size": size,
        }
        if quality:
            body["quality"] = quality
        if background:
            body["background"] = background

        async with session.post(
            f"{base_url}/v1/chat/completions",
            headers=self._auth_headers(json_request=True),
            json=body,
            timeout=timeout,
        ) as resp:
            return await self._read_json_response(resp)

    async def _read_json_response(self, resp: aiohttp.ClientResponse) -> Dict[str, Any]:
        raw_text = await resp.text()
        if resp.status != 200:
            raise RuntimeError(self._extract_error_message(raw_text) or f"HTTP {resp.status}")
        try:
            return json.loads(raw_text)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"响应不是合法 JSON: {exc}") from exc

    @staticmethod
    def _extract_error_message(raw_text: str) -> str:
        text = (raw_text or "").strip()
        if not text:
            return ""
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            return text[:300]
        if isinstance(payload, dict):
            error_obj = payload.get("error")
            if isinstance(error_obj, dict):
                return str(error_obj.get("message", "")).strip() or text[:300]
            if isinstance(error_obj, str):
                return error_obj.strip()
            message = payload.get("message")
            if isinstance(message, str):
                return message.strip()
        return text[:300]

    async def _extract_first_image(self, payload: Dict[str, Any]) -> Optional[Tuple[Optional[str], bytes]]:
        data_items = payload.get("data")
        if isinstance(data_items, list):
            for item in data_items:
                parsed = await self._extract_image_from_item(item)
                if parsed:
                    return parsed

        output_items = payload.get("output")
        if isinstance(output_items, list):
            for item in output_items:
                if not isinstance(item, dict):
                    continue
                for key in ("result", "b64_json", "image_base64"):
                    value = item.get(key)
                    if isinstance(value, str) and value.strip():
                        try:
                            return None, base64.b64decode(value)
                        except Exception:
                            pass

        choices = payload.get("choices")
        if isinstance(choices, list):
            for choice in choices:
                if not isinstance(choice, dict):
                    continue
                message = choice.get("message") or {}
                if not isinstance(message, dict):
                    continue
                images = message.get("images")
                if isinstance(images, list):
                    for item in images:
                        parsed = await self._extract_image_from_item(item)
                        if parsed:
                            return parsed
                content = message.get("content")
                parsed = await self._extract_image_from_content(content)
                if parsed:
                    return parsed
        return None

    async def _extract_image_from_content(self, content: Any) -> Optional[Tuple[Optional[str], bytes]]:
        if isinstance(content, list):
            for item in content:
                if not isinstance(item, dict):
                    continue
                parsed = await self._extract_image_from_item(item)
                if parsed:
                    return parsed
        if isinstance(content, str):
            match = re.search(r"data:image/[^;]+;base64,([A-Za-z0-9+/=]+)", content)
            if match:
                try:
                    return None, base64.b64decode(match.group(1))
                except Exception:
                    return None
        return None

    async def _extract_image_from_item(self, item: Any) -> Optional[Tuple[Optional[str], bytes]]:
        if not isinstance(item, dict):
            return None

        direct_b64 = item.get("b64_json")
        if isinstance(direct_b64, str) and direct_b64.strip():
            try:
                return None, base64.b64decode(direct_b64)
            except Exception:
                return None

        image_url = item.get("image_url")
        if isinstance(image_url, dict):
            image_url = image_url.get("url")
        if isinstance(image_url, str) and image_url.strip():
            return await self._fetch_image_from_url(image_url.strip())

        url = item.get("url")
        if isinstance(url, str) and url.strip():
            return await self._fetch_image_from_url(url.strip())
        return None

    async def _fetch_image_from_url(self, url: str) -> Optional[Tuple[Optional[str], bytes]]:
        if url.startswith("data:") and "," in url:
            try:
                return url, base64.b64decode(url.split(",", 1)[1])
            except Exception:
                return None

        include_auth = False
        try:
            response_host = urlparse(url).netloc
            base_host = urlparse(self._normalize_base_url()).netloc
            include_auth = not response_host or response_host == base_host
        except Exception:
            include_auth = False

        payload = await self._download_bytes(url, include_auth=include_auth)
        if payload:
            return url, payload
        return None

    async def _save_and_send_image(self, event: AstrMessageEvent, source_url: str, image_bytes: bytes):
        mime_type = self._detect_mime_type(image_bytes)
        extension = self._extension_for_mime(mime_type)
        filename = f"gptimage2_{int(time.time())}_{uuid.uuid4().hex[:8]}.{extension}"
        save_dir = self.image_dir if self._save_images() else self.temp_dir
        file_path = (save_dir / filename).resolve()

        try:
            async with aiofiles.open(file_path, "wb") as handle:
                await handle.write(image_bytes)
            yield event.chain_result([Comp.Image.fromFileSystem(path=str(file_path))])
        except Exception as exc:
            logger.error(f"[gptimage2] 发送图片失败: {exc}")
            yield event.plain_result("❌ 图片发送失败，请查看日志")
        finally:
            if not self._save_images():
                try:
                    await asyncio.to_thread(file_path.unlink, True)
                except Exception:
                    pass

    @staticmethod
    def _extension_for_mime(mime_type: str) -> str:
        return {
            "image/png": "png",
            "image/jpeg": "jpg",
            "image/gif": "gif",
            "image/webp": "webp",
            "image/bmp": "bmp",
        }.get(mime_type, "png")

    @staticmethod
    def _translate_error(error: str) -> str:
        raw = (error or "").strip()
        if not raw:
            return "未知错误"
        if any("\u4e00" <= char <= "\u9fff" for char in raw):
            return raw[:200]
        lowered = raw.lower()
        translations = {
            "forbidden": "访问被拒绝，请检查 API 地址、Key 或 Cloudflare 配置",
            "unauthorized": "API Key 无效或已过期",
            "timeout": "请求超时，请稍后重试",
            "model not found": "模型不存在或当前通道未放行该模型",
            "no available channel for model": "当前没有可用的该模型通道",
            "connection refused": "连接被拒绝，请检查 NewAPI 地址",
            "stream is not supported": "当前图片兼容路由不支持流式模式",
        }
        for key, message in translations.items():
            if key in lowered:
                return message
        return raw[:200]
