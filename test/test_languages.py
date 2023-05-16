from email_reply_parser import EmailReplyParser


SUPPORTED_LANGUAGES = ['en', 'de', 'fr', 'es', 'nl', 'fi', 'ja']


def test_init():
    txt = open('test/emails/multi_header_de.txt', 'r').read()
    for language_code in SUPPORTED_LANGUAGES:
        parser = EmailReplyParser(language=language_code)
        print(parser.parse_reply(txt))

    parser = EmailReplyParser(language='un')
    print(parser.parse_reply(txt))

if __name__ == '__main__':
    test_init()