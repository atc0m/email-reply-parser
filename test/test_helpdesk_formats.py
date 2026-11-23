"""Quote headers and signatures as helpdesks deliver them: addresses removed, lines flattened
or wrapped, Markdown links. All examples are made up."""
import unittest

from email_reply_parser import EmailReplyParser


def reply(text, language='en'):
    return EmailReplyParser(language).parse_reply(text)


QUOTED = 'Hello Sam,\nThank you for contacting us. Your order has shipped and will arrive on Friday.'


class QuoteHeaderTest(unittest.TestCase):

    def test_mailto_tail_after_header(self):
        for tail in ('(mailto:shop@example.com)', '[](mailto:)', '<[](mailto:)>', '<mailto:shop@example.com>'):
            text = 'Where is my order?\n\nOn Wed, 11 Nov 2026 at 16:32, Shop <> wrote: ' + tail + '\n\n' + QUOTED
            self.assertEqual('Where is my order?', reply(text), tail)

    def test_mailto_on_other_lines_is_kept(self):
        text = 'Please reply to my other address.\nEmail: [](mailto:)\nIt is the one on the order.'
        self.assertEqual(text, reply(text))

    def test_header_in_the_middle_of_a_flattened_line(self):
        text = 'I still have not received it. Kind regards Sam On Wed, 11 Nov 2026, 16:32 Shop, wrote: ' \
               'Hello Sam, your order has shipped and will arrive on Friday.'
        self.assertEqual('I still have not received it. Kind regards Sam', reply(text))

    def test_header_wrapped_over_two_lines(self):
        text = 'I never received the refund\n\nOn Wed, Nov 18, 2026, 3:24 PM Shop Support <\nwrote:\n\n' + QUOTED
        self.assertEqual('I never received the refund', reply(text))

    def test_first_person_sentence_is_not_a_header(self):
        text = 'On 3 Nov 2026 at 10:01 I wrote: please cancel my order. Nobody answered, so I am asking again.'
        self.assertEqual(text, reply(text))

    def test_french_header_with_non_breaking_space(self):
        text = 'Je voudrais annuler ma commande.\n\nLe mar. 3 nov. 2026 à 10:01, Boutique <> a écrit\xa0:\n\n' \
               'Bonjour, votre commande a été expédiée.'
        self.assertEqual('Je voudrais annuler ma commande.', reply(text, 'fr'))

    def test_german_header_with_sender_after_the_verb(self):
        text = 'Ich möchte die Bestellung stornieren.\n\nAm 12.11.2026 um 10:01 schrieb Shop Kundenservice:\n\n' \
               'Guten Tag, Ihre Bestellung wurde versendet.'
        self.assertEqual('Ich möchte die Bestellung stornieren.', reply(text, 'de'))

    def test_german_sentence_with_geschrieben_is_not_a_header(self):
        text = 'Hallo,\nich habe wie geschrieben folgende Artikel bestellt:\nzwei Hosen und ein Hemd.'
        self.assertEqual(text, reply(text, 'de'))

    def test_scandinavian_header_with_english_parser(self):
        text = 'Jeg har ikke fått pakken.\n\nDen tors. 29. okt. 2026 kl. 13.35 skrev Butikk <>:\n\n' \
               'Hei, pakken din er sendt.'
        self.assertEqual('Jeg har ikke fått pakken.', reply(text))

    def test_outlook_block_flattened_into_one_line(self):
        text = 'Any update on this? From: Shop Sent: Sunday, 25 October 2026 14:49:02 To: Sam ' \
               'Subject: Re: Your order Hello Sam, your order has shipped.'
        self.assertEqual('Any update on this?', reply(text))

    def test_finnish_message_ending_with_header_is_not_emptied(self):
        text = 'Hei,\nen ole saanut tilaustani.\n\n3.11.2026 Kauppa kirjoitti:'
        self.assertIn('en ole saanut tilaustani.', reply(text, 'fi'))


class SignatureTest(unittest.TestCase):

    def test_rule_at_the_top_does_not_remove_the_message(self):
        text = '----------------------------------------------\n\nHello,\n\n' \
               'I received the first part of my order but the covers are missing. Will they come later?'
        self.assertIn('the covers are missing', reply(text))

    def test_rule_above_a_short_signature_still_removes_it(self):
        text = 'Please cancel my order.\n\n--\nSam Smith\nSales Manager'
        self.assertEqual('Please cancel my order.', reply(text))

    def test_list_items_are_not_signatures(self):
        text = 'I have two questions:\n-Can you please help locate my order,\n-and tell me when the refund ' \
               'will arrive on my card?'
        self.assertEqual(text, reply(text))

    def test_thanks_followed_by_a_sentence_is_kept(self):
        text = 'Thank you, but that does not answer my question about the missing item in my parcel.\n' \
               'Could you please look at the order again and let me know?'
        self.assertEqual(text, reply(text))

    def test_thanks_as_a_closing_is_removed_with_the_name(self):
        text = 'Please cancel my order.\n\nThanks,\nSam'
        self.assertEqual('Please cancel my order.', reply(text))

    def test_device_line_above_the_message(self):
        text = 'Sent from my iPhone\n\nHello, I bought a shawl but I thought I was buying the whole dress. ' \
               'I would like to return it.'
        self.assertIn('I would like to return it.', reply(text))

    def test_french_closing_at_the_end_of_a_one_line_message(self):
        text = 'Bonjour, je souhaite modifier mon abonnement car je ne reçois pas les bons parfums. Cordialement'
        self.assertIn('je souhaite modifier mon abonnement', reply(text, 'fr'))

    def test_or_information_does_not_cut_the_sentence(self):
        text = 'Do you have any update or information about when my order will be delivered to me?'
        self.assertEqual(text, reply(text))

    def test_follow_up_notice_removes_only_itself(self):
        text = 'Hello\nThis is a follow-up to your previous request #123 "Order"\nI still need help with my return.'
        self.assertIn('I still need help with my return.', reply(text))


class EmptyReplyTest(unittest.TestCase):

    def test_forward_without_a_note_keeps_the_forwarded_text(self):
        text = 'On Tue, 3 Nov 2026 at 10:01, Sam Smith <> wrote:\n\n' \
               'Hello, my parcel arrived damaged and I would like a replacement please.'
        self.assertIn('my parcel arrived damaged', reply(text))

    def test_message_quoted_on_every_line_is_kept(self):
        text = '> Hello, my parcel arrived damaged\n> and I would like a replacement please.'
        self.assertIn('my parcel arrived damaged', reply(text))

    def test_quote_from_a_support_desk_is_not_returned(self):
        text = 'On Tue, 3 Nov 2026 at 10:01, Shop Customer Support <> wrote:\n\n' + QUOTED
        self.assertNotIn('Your order has shipped', reply(text))


if __name__ == '__main__':
    unittest.main()
