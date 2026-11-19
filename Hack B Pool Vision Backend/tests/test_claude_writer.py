"""ClaudeWriter against a stand-in for the Anthropic SDK: what is sent, and what comes back as a line."""
import unittest
from types import SimpleNamespace as NS

from app.commentator import MODEL, PERSONA, ClaudeWriter, Request


class Stream:
    def __init__(self, texts, stop, clock=None, step=0.0):
        self.texts, self.stop, self.clock, self.step = texts, stop, clock, step

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def __iter__(self):
        for t in self.texts:
            if self.clock:
                self.clock.now += self.step
            yield NS(type="text", text=t)

    def get_final_message(self):
        return NS(stop_reason=self.stop, usage=NS(input_tokens=500, output_tokens=20))


class Client:
    def __init__(self, stream):
        self.stream, self.sent, self.options = stream, None, None
        self.messages = self

    def with_options(self, **options):
        self.options = options
        return self

    def stream(self, **kwargs):  # replaced per instance in __init__
        raise NotImplementedError


def client_for(stream):
    c = Client(stream)

    def messages_stream(**kwargs):
        c.sent = kwargs
        return stream
    c.messages = NS(stream=messages_stream)
    return c


class Clock:
    now = 0.0

    def __call__(self):
        return self.now


def ask(client, clock=None):
    got = []
    writer = ClaudeWriter(client, spawn=lambda work, *args: work(*args), clock=clock or Clock())
    writer.ask(Request("shot", MODEL, PERSONA, {"x": 1}), got.append)
    return got[0], writer


class ClaudeWriterTest(unittest.TestCase):
    def test_haiku_streamed_thinking_off_low_effort_no_retries(self):
        client = client_for(Stream(["Nicely ", "done."], "end_turn"))
        line, writer = ask(client)
        self.assertEqual(line, "Nicely done.")
        self.assertEqual(client.sent["model"], "claude-haiku-5-5")
        self.assertEqual(client.sent["thinking"], {"type": "disabled"})
        self.assertEqual(client.sent["output_config"], {"effort": "low"})
        self.assertEqual(client.sent["system"], PERSONA)
        self.assertEqual(client.options, {"timeout": 5.0, "max_retries": 0})
        self.assertEqual(writer.usage, {"input_tokens": 500, "output_tokens": 20, "requests": 1})

    def test_a_refusal_is_no_line(self):
        self.assertIsNone(ask(client_for(Stream(["no"], "refusal")))[0])

    def test_cut_short_keeps_whole_sentences(self):
        self.assertEqual(ask(client_for(Stream(["One. Two and"], "max_tokens")))[0], "One.")

    def test_too_slow_is_given_up(self):
        clock = Clock()
        self.assertIsNone(ask(client_for(Stream(["a ", "b ", "c."], "end_turn", clock, step=3)), clock)[0])

    def test_an_error_is_no_line(self):
        def boom(**kwargs):
            raise ConnectionError("down")
        client = Client(None)
        client.messages = NS(stream=boom)
        self.assertIsNone(ask(client)[0])


if __name__ == "__main__":
    unittest.main()
