"""
scripts/translate.py

Dịch câu đơn hoặc file với model đã fine-tune.

Usage:
    # Câu đơn
    python scripts/translate.py --text "会議は午後3時に始まります。" --src ja --tgt vi

    # File
    python scripts/translate.py --src-file input.txt --src ja --tgt vi --out output.txt

    # Với debug chi tiết (chunk breakdown)
    python scripts/translate.py --text "..." --src ja --tgt vi --debug

    # Dùng fine-tuned model
    python scripts/translate.py --text "..." --model models/finetuned/best --src ja --tgt vi
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.translator.contextual_translator import ContextualTranslator
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

console = Console()


def print_chunk_debug(details: dict):
    """In bảng chunk breakdown đẹp."""
    console.print(Panel(f"[bold cyan]Input:[/bold cyan] {details['original']}"))
    console.print(f"[dim]{details['src_lang']} → {details['tgt_lang']}[/dim]\n")

    table = Table(title="Chunk Breakdown")
    table.add_column("#", style="dim", width=3)
    table.add_column("Chunk (src)", style="yellow")
    table.add_column("Type", style="cyan", width=6)
    table.add_column("Role", style="blue", width=8)
    table.add_column("Pos", style="dim", width=5)
    table.add_column("Weight", style="green", width=7)
    table.add_column("Translated", style="white")

    for i, chunk in enumerate(details["chunks"]):
        table.add_row(
            str(i + 1),
            chunk["chunk"],
            chunk["type"],
            chunk["dep_role"],
            f"{chunk['position_ratio']:.2f}",
            f"{chunk['context_weight']:.2f}",
            chunk["translated"],
        )

    console.print(table)
    console.print(
        Panel(
            f"[bold green]Final Translation:[/bold green] {details['final_translation']}",
            border_style="green",
        )
    )


def main():
    parser = argparse.ArgumentParser(description="Contextual NLLB Translator")
    parser.add_argument("--text", help="Single sentence to translate")
    parser.add_argument("--src-file", help="Input file (1 sentence/line)")
    parser.add_argument("--out", help="Output file for translated sentences")
    parser.add_argument("--src", default="ja", help="Source language (ja/en/vi)")
    parser.add_argument("--tgt", default="vi", help="Target language (ja/en/vi)")
    parser.add_argument("--model", default="facebook/nllb-200-distilled-600M")
    parser.add_argument("--debug", action="store_true", help="Show chunk breakdown")
    parser.add_argument("--no-chunks", action="store_true", help="Disable chunk prefix (baseline mode)")
    parser.add_argument("--beams", type=int, default=4)
    args = parser.parse_args()

    console.print(f"[bold]Loading model:[/bold] {args.model}")
    translator = ContextualTranslator(
        model_path=args.model,
        use_chunk_prefix=not args.no_chunks,
    )

    if args.text:
        if args.debug:
            details = translator.translate_with_details(args.text, args.src, args.tgt)
            print_chunk_debug(details)
        else:
            result = translator.translate_sentence(args.text, args.src, args.tgt, num_beams=args.beams)
            console.print(f"\n[bold green]Translation:[/bold green] {result}")

    elif args.src_file:
        src_path = Path(args.src_file)
        sentences = src_path.read_text(encoding="utf-8").strip().splitlines()
        console.print(f"Translating {len(sentences)} sentences ({args.src} → {args.tgt})...")

        translations = []
        for i, sent in enumerate(sentences):
            t = translator.translate_sentence(sent, args.src, args.tgt, num_beams=args.beams)
            translations.append(t)
            if (i + 1) % 10 == 0:
                console.print(f"  {i+1}/{len(sentences)}")

        if args.out:
            Path(args.out).write_text("\n".join(translations), encoding="utf-8")
            console.print(f"\nSaved to: {args.out}")
        else:
            for t in translations:
                print(t)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
