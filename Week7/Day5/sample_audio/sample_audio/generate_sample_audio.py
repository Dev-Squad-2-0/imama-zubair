import asyncio
import os
import sys
import traceback

import edge_tts

OUT_DIR = os.path.dirname(os.path.abspath(__file__))
VOICE = os.getenv("EDGE_TTS_VOICE", "ur-PK-AsadNeural")

UTTERANCES = {
    "01_budget_3_crore.mp3": "میرا بجٹ تین کروڑ ہے۔",
    "02_dha_area_query.mp3": "ڈی ایچ اے میں کون سے گھر دستیاب ہیں؟",
    "03_price_objection.mp3": "یہ پراپرٹی تھوڑی مہنگی ہے۔",
    "04_cheaper_option.mp3": "اس سے سستا کوئی آپشن ہے؟",
    "05_investment_question.mp3": "انویسٹمنٹ کے حساب سے کتنا پروفٹ ہوگا؟",
    "06_trust_concern.mp3": "مجھے اس بلڈر پر بھروسہ نہیں ہے۔",
}


async def _synthesize_mp3(text: str, output_path: str, voice: str):
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(output_path)


def main():
    print(f"Saving MP3 files to:\n{OUT_DIR}\n")

    for filename, text in UTTERANCES.items():
        output_path = os.path.join(OUT_DIR, filename)

        print(f"Synthesizing: {text!r}")
        try:
            asyncio.run(_synthesize_mp3(text, output_path, VOICE))
            print(f"  ✓ Saved: {output_path}")

        except Exception as e:
            print(f"  FAILED: {repr(e)}")
            traceback.print_exc()

    print("\nDone!")


if __name__ == "__main__":
    main()