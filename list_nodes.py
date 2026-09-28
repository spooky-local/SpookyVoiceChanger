#!/usr/bin/env python3
"""
Lists the audio-loading nodes in your exported workflow so you can tell
tts_service.py which one to feed your microphone recording into.

Run it from the TTS folder:

    python list_nodes.py
"""

import json
import os
import sys

# Looked for next to this script, so the folder stays portable.
WORKFLOW_JSON = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "workflow_api.json"
)

LOADER_HINTS = ("loadaudio", "load_audio", "loadaudiofrompath")
FILE_KEYS = ("audio", "audio_file", "file", "path")


def titles_from_editor_workflow(api_path):
    """Read node titles from workflow.json sitting beside the API export.

    ComfyUI only writes titles into the API export on some frontend
    versions, but the editor format always has them.
    """
    folder = os.path.dirname(os.path.abspath(api_path))
    for name in ("workflow.json", "workflow_ui.json"):
        candidate = os.path.join(folder, name)
        if not os.path.isfile(candidate):
            continue
        try:
            with open(candidate, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            continue

        nodes = data.get("nodes")
        if not isinstance(nodes, list):
            continue

        found = {}
        for node in nodes:
            if not isinstance(node, dict) or "id" not in node:
                continue
            title = node.get("title")
            if title:
                found[str(node["id"])] = title
        if found:
            return found, name

    return {}, None


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else WORKFLOW_JSON

    if not os.path.isfile(path):
        print(f"Not found: {path}")
        sys.exit(1)

    with open(path, "r", encoding="utf-8") as f:
        graph = json.load(f)

    if "prompt" in graph and "nodes" not in graph:
        graph = graph["prompt"]

    extra_titles, title_source = titles_from_editor_workflow(path)

    loaders = []
    for node_id, node in graph.items():
        ct = node.get("class_type", "")
        if any(h in ct.lower().replace(" ", "") for h in LOADER_HINTS):
            current = ""
            for key in FILE_KEYS:
                val = node.get("inputs", {}).get(key)
                if isinstance(val, str):
                    current = val
                    break
            title = (node.get("_meta", {}).get("title")
                     or node.get("title")
                     or extra_titles.get(str(node_id), ""))
            loaders.append((node_id, ct, current, title))

    if not loaders:
        print("No audio loader nodes found in this workflow.")
        sys.exit(1)

    print(f"\nAudio loader nodes in {os.path.basename(path)}:")
    if title_source:
        print(f"(titles read from {title_source})")
    print()
    for node_id, ct, current, title in loaders:
        label = f"{ct}   \"{title}\"" if title and title != ct else ct
        print(f"  Node ID {node_id}   {label}")
        print(f"      currently loads: {current or '(nothing)'}")
        print(f"      feeds: {', '.join(consumers(graph, node_id)) or '(nothing)'}")
        print()

    print("Pick the one whose file is the SPEECH you want spoken,")
    print("not the one that is your voice reference.")
    print("\nThen open tts_service.py and set, for example:")
    print(f'    AUDIO_INPUT_NODE = "{loaders[0][0]}"\n')


def consumers(graph, node_id):
    """Which nodes take input from this one."""
    out = []
    for other_id, other in graph.items():
        for value in other.get("inputs", {}).values():
            if isinstance(value, list) and value and str(value[0]) == str(node_id):
                label = other.get("class_type", other_id)
                if label not in out:
                    out.append(label)
    return out


if __name__ == "__main__":
    main()
