"""
Agnes AI client — OpenAI-compatible wrapper for:
  - Chat completions with tool calling (Agnes 2.0 Flash)
  - Thinking mode for deep synthesis
  - Image generation (Agnes Image 2.1 Flash)
  - Async video generation with polling (Agnes Video V2.0)
"""

import os
import json
import time
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional, List, Dict, Any

AGNES_BASE_URL = "https://apihub.agnes-ai.com/v1"
VIDEO_BASE_URL = "https://apihub.agnes-ai.com"

DEFAULT_TEXT_MODEL  = "agnes-2.0-flash"
DEFAULT_IMAGE_MODEL = "agnes-image-2.1-flash"
DEFAULT_VIDEO_MODEL = "agnes-video-v2.0"


class AgnesClient:
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.environ.get("AGNES_API_KEY", "")
        if not self.api_key:
            raise ValueError("AGNES_API_KEY is not set. Export it or pass api_key=")
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    # ------------------------------------------------------------------ #
    # Chat / Synthesis
    # ------------------------------------------------------------------ #

    def chat(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict]] = None,
        thinking: bool = False,
        model: str = DEFAULT_TEXT_MODEL,
        max_tokens: int = 8192,
        temperature: float = 0.7,
        **kwargs,
    ) -> Dict:
        """
        Call Agnes 2.0 Flash chat completions.

        Args:
            messages:    OpenAI-style message list
            tools:       Tool definitions for function calling
            thinking:    Enable Thinking mode (better synthesis quality)
            model:       Model override
            max_tokens:  Max tokens to generate
            temperature: Sampling temperature
        Returns:
            Raw API response dict
        """
        payload: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            **kwargs,
        }
        if tools:
            payload["tools"] = tools
        if thinking:
            payload["chat_template_kwargs"] = {"enable_thinking": True}

        resp = requests.post(
            f"{AGNES_BASE_URL}/chat/completions",
            headers=self.headers,
            json=payload,
            timeout=120,
        )
        resp.raise_for_status()
        return resp.json()

    def get_message_content(self, response: Dict) -> str:
        """Extract text content from a chat response."""
        return response["choices"][0]["message"]["content"] or ""

    def get_tool_calls(self, response: Dict) -> Optional[List[Dict]]:
        """Extract tool calls from a chat response, or None if not present."""
        msg = response["choices"][0]["message"]
        return msg.get("tool_calls")

    def finish_reason(self, response: Dict) -> str:
        return response["choices"][0].get("finish_reason", "")

    # ------------------------------------------------------------------ #
    # Agentic Loop Helper
    # ------------------------------------------------------------------ #

    def run_agent(
        self,
        system_prompt: str,
        user_message: str,
        tools: List[Dict],
        tool_executor,          # callable(name: str, args: dict) -> str
        thinking: bool = True,
        max_iterations: int = 20,
    ) -> str:
        """
        Run an agentic tool-calling loop until the model stops calling tools.

        Args:
            system_prompt:  System message
            user_message:   Initial user message
            tools:          Tool definitions
            tool_executor:  Function that executes a named tool and returns a string result
            thinking:       Enable Thinking mode
            max_iterations: Safety cap on tool call rounds
        Returns:
            Final text response from the model
        """
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_message},
        ]

        for _ in range(max_iterations):
            response = self.chat(messages, tools=tools, thinking=thinking)
            tool_calls = self.get_tool_calls(response)

            # No more tool calls — return the final answer
            if not tool_calls:
                return self.get_message_content(response)

            # Append assistant message with tool calls
            messages.append(response["choices"][0]["message"])

            # Execute all tool calls in parallel when there are multiple
            if len(tool_calls) == 1:
                call = tool_calls[0]
                results = {call["id"]: tool_executor(call["function"]["name"], json.loads(call["function"]["arguments"]))}
            else:
                with ThreadPoolExecutor(max_workers=len(tool_calls)) as pool:
                    futures = {
                        pool.submit(
                            tool_executor,
                            call["function"]["name"],
                            json.loads(call["function"]["arguments"]),
                        ): call["id"]
                        for call in tool_calls
                    }
                    results = {call_id: f.result() for f, call_id in futures.items()}

            for call in tool_calls:
                messages.append({
                    "role":         "tool",
                    "tool_call_id": call["id"],
                    "name":         call["function"]["name"],
                    "content":      results[call["id"]],
                })

        # Fallback: ask for a final answer without tools
        messages.append({"role": "user", "content": "Please provide your final synthesis now."})
        return self.get_message_content(self.chat(messages, thinking=thinking))

    # ------------------------------------------------------------------ #
    # Image Generation
    # ------------------------------------------------------------------ #

    def generate_image(
        self,
        prompt: str,
        size: str = "1024x768",
        model: str = DEFAULT_IMAGE_MODEL,
        return_base64: bool = False,
    ) -> str:
        """
        Generate an image via Agnes Image 2.1 Flash.

        Args:
            prompt:        Text description of the image
            size:          Output size, e.g. "1024x768" or "1024x1024"
            model:         Model override (agnes-image-2.0-flash or agnes-image-2.1-flash)
            return_base64: If True, return base64 string instead of URL
        Returns:
            Image URL or base64 string
        """
        payload: Dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "size": size,
        }
        if return_base64:
            payload["return_base64"] = True
        else:
            payload["extra_body"] = {"response_format": "url"}

        resp = requests.post(
            f"{AGNES_BASE_URL}/images/generations",
            headers=self.headers,
            json=payload,
            timeout=180,
        )
        resp.raise_for_status()
        data = resp.json()["data"][0]
        return data.get("b64_json") if return_base64 else data.get("url")

    def edit_image(
        self,
        prompt: str,
        image_urls: List[str],
        size: str = "1024x768",
        model: str = DEFAULT_IMAGE_MODEL,
    ) -> str:
        """
        Edit or compose images via Agnes Image 2.1 Flash (image-to-image).

        Args:
            prompt:     Editing instruction
            image_urls: List of input image URLs (public HTTPS or data URIs)
            size:       Output size
        Returns:
            Generated image URL
        """
        payload = {
            "model": model,
            "prompt": prompt,
            "size": size,
            "extra_body": {
                "image": image_urls,
                "response_format": "url",
            },
        }
        resp = requests.post(
            f"{AGNES_BASE_URL}/images/generations",
            headers=self.headers,
            json=payload,
            timeout=180,
        )
        resp.raise_for_status()
        return resp.json()["data"][0]["url"]

    # ------------------------------------------------------------------ #
    # Video Generation
    # ------------------------------------------------------------------ #

    def generate_video(
        self,
        prompt: str,
        image_url: Optional[str] = None,
        keyframe_urls: Optional[List[str]] = None,
        num_frames: int = 121,
        frame_rate: int = 24,
        width: int = 1152,
        height: int = 768,
        poll_interval: int = 8,
        max_wait: int = 600,
    ) -> str:
        """
        Generate a video via Agnes Video V2.0 (async task-based).

        Args:
            prompt:        Text description of the video
            image_url:     Single image URL for image-to-video
            keyframe_urls: List of image URLs for keyframe animation
            num_frames:    Number of frames (must follow 8n+1 rule, max 441)
            frame_rate:    FPS (1–60)
            width/height:  Output dimensions (auto-snapped to nearest standard)
            poll_interval: Seconds between status polls
            max_wait:      Max total seconds to wait for completion
        Returns:
            URL of the generated video
        Raises:
            RuntimeError on generation failure
            TimeoutError if max_wait exceeded
        """
        payload: Dict[str, Any] = {
            "model": DEFAULT_VIDEO_MODEL,
            "prompt": prompt,
            "num_frames": num_frames,
            "frame_rate": frame_rate,
            "width": width,
            "height": height,
        }

        if keyframe_urls:
            payload["extra_body"] = {"image": keyframe_urls, "mode": "keyframes"}
        elif image_url:
            payload["image"] = image_url

        # Submit task
        resp = requests.post(
            f"{VIDEO_BASE_URL}/v1/videos",
            headers=self.headers,
            json=payload,
            timeout=60,
        )
        resp.raise_for_status()
        task = resp.json()
        video_id = task.get("video_id") or task.get("id")
        if not video_id:
            raise RuntimeError(f"No video_id in task response: {task}")

        # Poll for completion
        elapsed = 0
        while elapsed < max_wait:
            time.sleep(poll_interval)
            elapsed += poll_interval

            poll = requests.get(
                f"{VIDEO_BASE_URL}/agnesapi?video_id={video_id}",
                headers=self.headers,
                timeout=30,
            )
            result = poll.json()
            status = result.get("status")

            if status == "completed":
                url = result.get("remixed_from_video_id")
                if not url:
                    raise RuntimeError("Completed but no video URL in response")
                return url

            if status == "failed":
                raise RuntimeError(f"Video generation failed: {result.get('error')}")

            # Still in progress — keep polling
            progress = result.get("progress", 0)
            print(f"  Video: {status} ({progress}%) — {elapsed}s elapsed", flush=True)

        raise TimeoutError(f"Video generation timed out after {max_wait}s (video_id={video_id})")
