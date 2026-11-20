"""Chat with Adam in the terminal, as if you were a customer.

    python chat_cli.py            # new test conversation
    /reset                        # start over
    /file path/to/photo.jpg text  # send an image or PDF with a message
"""
import asyncio
import mimetypes
import sys
import uuid

from app import notify, store
from app.agent import IncomingMessage, handle_message


async def main() -> None:
    customer = "cli-" + uuid.uuid4().hex[:6]
    print("💬 اكتب رسالتك كزبون (Ctrl+C للخروج)\n")
    while True:
        try:
            line = input("👤 ").strip()
        except (EOFError, KeyboardInterrupt):
            return
        if not line:
            continue
        if line == "/reset":
            store.reset_conversation(customer)
            print("— محادثة جديدة —")
            continue
        msg = IncomingMessage(customer_id=customer, customer_name="Test")
        if line.startswith("/file "):
            parts = line.split(maxsplit=2)
            path = parts[1]
            mime = mimetypes.guess_type(path)[0] or "application/octet-stream"
            msg.media.append((open(path, "rb").read(), mime))
            msg.text = parts[2] if len(parts) > 2 else ""
        else:
            msg.text = line
        before = len(notify.test_log)
        reply = await handle_message(msg)
        print(f"\n🤖 {reply.text}")
        for url, _ in reply.photos:
            print(f"   🖼️  {url}")
        for n in notify.test_log[before:]:
            print(f"   🔔 [{n['kind']}] {n['summary']} {n['details'] or ''}")
        print()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
