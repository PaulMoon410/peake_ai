import unittest

import peakebot


class DateIntentTests(unittest.TestCase):
    def test_direct_date_questions_get_a_date_reply(self) -> None:
        response = peakebot._match_basic_interaction("what is the date?")

        self.assertRegex(response, r"^Today's date is .+\.$")

    def test_mentions_of_date_in_other_questions_do_not_get_date_reply(self) -> None:
        response = peakebot._match_basic_interaction(
            "can you fix why we keep getting so many outputs of the date?"
        )

        self.assertEqual("", response)


if __name__ == "__main__":
    unittest.main()
