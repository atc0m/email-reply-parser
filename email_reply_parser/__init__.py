"""
email_reply_parser is a python library port of GitHub's Email Reply Parser.
For more information, visit https://github.com/zapier/email_reply_parser
"""
import os
import re
import json


MAILTO_TAIL_REGEX = re.compile(
    r'(:)[ \t\xa0]*<?(?:\[[^\]\n]*\])?[(<]mailto:[^)>\n]*[)>]>?[ \t\xa0]*$', re.MULTILINE
)

# --- Strict quote headers, any language, anywhere in a line -------------------------------
# Helpdesks flatten emails ("... Sent from my iPhone On 3 Nov 2026, at 09:04, Shop wrote: Hi"),
# strip the sender's address, or glue the quoted text after the colon, so the per-language
# QUOTE_HDR_REGEX (which needs the header alone on its line) misses the header. The patterns
# below only accept a header that starts with a date (optional weekday / month word, then a
# day or year number) and are bounded per line, so they can be searched in the middle of a
# line. `_split_inline_headers` puts each such header on its own line.
_HDR_DATE_HEAD = r'(?:[^\W\d_]{2,10}\.?,?\s){0,2}(?:\d{1,2}(?!\d)|(?:19|20)\d{2}(?!\d))'
_HDR_DATE_SHAPE = re.compile(r'(?:19|20)\d{2}(?!\d)|\d{1,2}\s?[:.h]\s?\d{2}(?!\d)')
_HDR_TIME_SHAPE = re.compile(r'\d{1,2}\s?[:.]\s?\d{2}(?!\d)')
_HDR_FIRST_PERSON = re.compile(r'(?:^|[\s,])(?:I|we|you)\s*$', re.IGNORECASE)
_HDR_PRONOUN_SENDER = re.compile(
    r'\s*(?:ich|wir|er|sie|man|mir|ihnen|euch|ik|wij|we|u|je|jij|hij|zij|jeg|jag|vi|du|han|hun|hon)\b',
    re.IGNORECASE)

_HDR_NORDIC_DATE = (
    r'(?<![0-9])(?:(?:Den|P\u00e5)\s)?'
    r'(?:(?:man|m\u00e5n|tir|tis|ons|tor|fre|l\u00f8r|l\u00f6r|s\u00f8n|s\u00f6n)[a-z\u00e6\u00f8\u00e5\u00f6]{0,6}\.?,?\s)?(?:den\s)?'
    r'(?:\d{1,2}\.?\s[a-z\u00e6\u00f8\u00e5]{3,9}\.?\s(?:19|20)\d{2}|(?:19|20)\d{2}-\d{2}-\d{2}|\d{1,2}[./]\d{1,2}[./]\d{2,4})')


def _sender_verb_header(start, verb):
    """ "On <date> <sender> wrote:" - the sender comes before the verb, the colon ends it. """
    start_regex = re.compile(r'(?<![A-Z])(?:' + start + r')\s')
    pattern = re.compile(
        r'(?<![A-Z])(?:' + start + r')\s' + _HDR_DATE_HEAD
        + r'[^\n]{2,170}?(?<![^\W\d_])(?:' + verb + r')\s*:')
    return start_regex, pattern, re.compile(r'(?:' + verb + r')\s*:$')


def _verb_sender_header(start, verb):
    """ "Am <date> schrieb <sender>:" - the sender follows the verb; with the address removed
        the line may end at the sender, without the colon.
    """
    return re.compile(
        r'(?<![A-Z])(?:' + start + r')\s' + _HDR_DATE_HEAD
        + r'[^\n]{0,60}?\s(?:' + verb + r')(?P<sender>\s[^\n:]{0,100})?(?P<end>:|$)')


# keyword that must be in the line -> compiled header patterns
_HDR_SENDER_VERB = {
    'wrote': _sender_verb_header('On', 'wrote'),
    '\u00e9crit': _sender_verb_header('Le', r'a\s?\u00e9crit'),
    'escribi\u00f3': _sender_verb_header('El', 'escribi\u00f3'),
    'escreveu': _sender_verb_header('Em', 'escreveu'),
    'ha scritto': _sender_verb_header('Il(?: giorno)?', 'ha scritto'),
    'napisa\u0142': _sender_verb_header('W dniu', r'napisa\u0142(?:\(a\))?'),
}
_HDR_VERB_SENDER = {
    'schrieb': [_verb_sender_header('Am', 'schrieb')],
    'schreef': [_verb_sender_header('Op', 'schreef')],
    # Danish / Norwegian / Swedish: "(Den) (tors.) 29. okt. 2026 kl. 13.35 skrev <sender>:",
    # "Den tis 3 nov. 2026 09:08 <sender> skrev:"
    'skrev': [
        re.compile(_HDR_NORDIC_DATE + r'[^\n]{0,30}?\sskrev(?P<sender>\s[^\n:]{0,100})?(?P<end>:|$)'),
        re.compile(_HDR_NORDIC_DATE + r'(?P<sender>[^\n:]{0,25}(?::\d{2}[^\n:]{0,100})?)\sskrev\s*(?P<end>:)'),
    ],
}

# Outlook-style header block flattened into one line by the helpdesk:
# "... Sent from Outlook for iOS From: Shop Sent: Sunday, 25 October 2026 14:49:02 To: Me Subject: Re: x"
# All four labels are required, in order, with a date after the second one. A forward
# ("Begin forwarded message: From: ...", "Subject: Fw: ...") is left alone: its body may be
# the customer's request.
_HDR_BLOCK = re.compile(
    r'(?<![^\W\d_])(?:From|Von|De|Van|Da|Fr\u00e5n|Fra)\s?:(?P<sender>[^\n]{0,120}?)'
    r'(?<![^\W\d_])(?:Sent|Date|Gesendet|Datum|Envoy\u00e9|Enviado(?: el)?|Verzonden|Inviato|Data|Skickat|Sendt)\s?:'
    r'(?P<date>[^\n]{6,70}?)'
    r'(?<![^\W\d_])(?:To|An|\u00c0|A|Para|Aan|Til|Till)\s?:[^\n]{0,200}?'
    r'(?<![^\W\d_])(?:Subject|Betreff|Objet|Asunto|Assunto|Onderwerp|Oggetto|\u00c4mne|Emne)\s?:'
    r'(?P<subject>[^\n]{0,40})')
_HDR_BLOCK_KEYWORDS = ('Subject', 'Betreff', 'Objet', 'Asunto', 'Assunto', 'Onderwerp', 'Oggetto',
                       '\u00c4mne', 'Emne')
_HDR_FORWARD_SUBJECT = re.compile(
    r'\s*(?:\[[^\]\n]{0,20}\]\s*:?\s*)?(?:(?:re|aw|sv)\s?:\s*)?(?:fwd?|wg|tr|rv|enc|doorst|vs|vb)\s?:', re.IGNORECASE)
_HDR_FORWARD_MARKER = re.compile(
    r'(?:forwarded message|weitergeleitete nachricht|message transf\u00e9r\u00e9|mensaje reenviado'
    r'|mensagem encaminhada|doorgestuurd bericht|messaggio inoltrato|vidarebefordrat|videresendt)'
    r'[\s:*-]*$', re.IGNORECASE)


def _find_inline_block(line):
    """ Returns the start of an Outlook-style reply header block inside line, or None. """
    if not any(keyword in line for keyword in _HDR_BLOCK_KEYWORDS):
        return None
    for match in _HDR_BLOCK.finditer(line):
        if not _HDR_DATE_SHAPE.search(match.group('date')):
            continue
        if _HDR_FORWARD_SUBJECT.match(match.group('subject')) \
                or _HDR_FORWARD_MARKER.search(line[:match.start()]):
            return None
        return match.start()
    return None


def _find_inline_header(line):
    """ Returns (start, end) of the first strict quote header in line, or None. """
    best = None
    for keyword, (start_regex, pattern, verb_end) in _HDR_SENDER_VERB.items():
        if keyword not in line:
            continue
        match = pattern.search(line)
        while match:
            first, end = match.span()
            start = first
            # The lazy match starts at the first date-like "On ..."; the header is the last one
            # that still reaches the same verb ("On 3 Nov I ordered ... On 5 Nov 2026 X wrote:").
            for later in start_regex.finditer(line, first + 1, end):
                retry = pattern.match(line, later.start())
                if retry and retry.end() == end and _HDR_DATE_SHAPE.search(retry.group()) \
                        and not line[first:retry.start()].endswith('mailto:'):
                    # (a header repeated inside its own "[](mailto:" link is one header)
                    start = retry.start()
            if line.startswith('El El ', start - 3):
                start -= 3  # Gmail in Spanish: "El El jue, nov 12, 2026 ..."
            header = line[start:end]
            if _HDR_DATE_SHAPE.search(header) and not _HDR_FIRST_PERSON.search(verb_end.sub('', header)):
                if best is None or start < best[0]:
                    best = (start, end)
                break
            match = pattern.search(line, end)
    for keyword, patterns in _HDR_VERB_SENDER.items():
        if keyword not in line:
            continue
        for pattern in patterns:
            for match in pattern.finditer(line):
                header = match.group()
                sender = match.group('sender') or ''
                if not _HDR_DATE_SHAPE.search(header) or _HDR_PRONOUN_SENDER.match(sender):
                    continue
                if not match.group('end') and (
                        not _HDR_TIME_SHAPE.search(header) or len(sender) > 70
                        or sender.rstrip()[-1:] in ('.', '!', '?')):
                    # No colon: only a line that ends at the sender, with a time in the date.
                    continue
                if best is None or match.start() < best[0]:
                    best = match.span()
                break
    block = _find_inline_block(line)
    if block is not None and (best is None or block < best[0]):
        best = (block, len(line))
    return best


def _is_broken_quote(lines):
    """ True when few of the lines after a quoted header are quoted themselves. A reply that
        is quoted line by line may have the customer's answer below or between the quotes,
        and is left to the fragment logic.
    """
    total = quoted = 0
    for line in lines:
        text = line.strip()
        if not text.strip('> \t\ufeff'):
            continue
        total += 1
        quoted += text.startswith('>')
    return total >= 4 and quoted * 3 < total


def _starts_marked_quote(lines):
    """ True when the first paragraph in lines is quoted (">") on every line: two lines or
        more, or a single line when the rest is not a broken quote either.
    """
    paragraph = []
    for line in lines:
        if line.strip():
            paragraph.append(line)
        elif paragraph:
            break
    if not paragraph or not all(line.lstrip().startswith('>') for line in paragraph):
        return False
    return len(paragraph) >= 2 or not _is_broken_quote(lines)


_HDR_WRAPPED_VERB = re.compile(
    r'[^\n:]{0,60}?(?<![^\W\d_])(?:wrote|(?:a\s?)?\u00e9crit|escribi\u00f3|escreveu|ha scritto|napisa\u0142(?:\(a\))?|skrev)\s*:')


def _join_wrapped_headers(lines):
    """ Joins a header whose verb and colon wrapped to the next line:
        "On Wed, Nov 18, 2026, 3:24 PM Shop Support <" / "wrote:".
    """
    lines = list(lines)
    seen_text = False
    for index in range(len(lines) - 1):
        tail = lines[index + 1].strip()
        head = lines[index].rstrip()
        if not seen_text:
            # A header that opens the message is left as it is (see _split_inline_headers).
            seen_text = bool(head.strip())
            continue
        if not tail or not _HDR_WRAPPED_VERB.match(tail):
            continue
        if not head or len(head) > 400 or _find_inline_header(head) is not None:
            continue
        found = _find_inline_header(head + ' ' + tail)
        if found is not None and found[0] < len(head) < found[1]:
            lines[index] = head + ' ' + tail
            lines[index + 1] = ''
    return lines


def _split_inline_headers(lines):
    """ Puts every strict quote header on its own line.
        Returns (lines, header lines, header lines that hide everything below them).
    """
    result, headers, forced = [], set(), set()
    seen_text = seen_quoted = False
    lines = _join_wrapped_headers(lines)
    for index, line in enumerate(lines):
        found = _find_inline_header(line)
        if found is None:
            result.append(line)
            seen_text = seen_text or bool(line.strip())
            seen_quoted = seen_quoted or line.lstrip().startswith('>')
            continue
        start, end = found
        before = line[:start].strip()
        if before and not before.strip('> ') and not seen_quoted \
                and _is_broken_quote(lines[index + 1:]):
            # Apple Mail puts the header inside the quote ("> On ... wrote:") and helpdesks
            # keep the ">" on the first line of each paragraph only, so the rest of the quote
            # looks like the customer's text. When the first quoted line of the message is
            # the header, it is the header of the whole quote.
            before = ''
            line = line[start:]
            end -= start
            start = 0
        seen_quoted = seen_quoted or before.startswith('>')
        if before.startswith('>') or not (seen_text or before):
            # A header inside a quoted line stays part of that quote. A header that opens the
            # message has nothing above it to keep (an empty reply, or a forward whose body is
            # the request), so it is left to the per-language patterns as before.
            result.append(line)
            seen_text = True
            continue
        header = line[start:end].strip()
        headers.add(header)
        if not _starts_marked_quote([line[end:]] + lines[index + 1:]):
            # Followed by a quote that is marked line by line, the header stays part of that
            # quote and text between or below the quoted lines is kept (inline replies).
            # Otherwise nothing marks where the quote ends: everything below is hidden.
            forced.add(header)
        result.extend(part for part in (line[:start], header, line[end:]) if part.strip())
    return result, headers, forced

# --- Signature review ------------------------------------------------------------------------
# SIG_REGEX marks a fragment as a signature from its first line alone ("--", "-word",
# "Thanks,", "Sent from ...") and the reply drops every signature fragment, wherever it is.
# Losing the customer's text is worse than keeping a signature, so each signature fragment is
# reviewed once the whole message is known (see EmailMessage._review_signatures).
_SIG_SEPARATOR = re.compile(r'[-_]{2,}')
_SIG_DEVICE = re.compile(
    r'(?:sent from|sent via|get outlook|enviado desde|enviado de|envoy\u00e9 de|envoy\u00e9 depuis'
    r'|gesendet von|von meinem|verstuurd vanaf|verzonden vanaf|inviato da|skickat fr\u00e5n|sendt fra'
    r'|l\u00e4hetetty|hanki outlook)\b', re.IGNORECASE)
_SIG_CONTINUES = re.compile(
    r'(?:I|i|we|you|but|for|and|so|that|this|it|if|please|can|could|will|is|aber|f\u00fcr|und|dass|ich|wir'
    r'|maar|voor|en|ik|mais|pour|et|je|de|que)\b|I\'')
_SIG_THREAD_LABEL = re.compile(
    r'[>*\s]*(?:From|Von|De|Van|Da|Fr\u00e5n|Fra|Sent|Date|Datum|Dato|Gesendet|Envoy\u00e9|Enviado|Verzonden'
    r'|Subject|Betreff|Objet|Asunto|Assunto|Onderwerp|Emne|\u00c4mne|To|An|\u00c0|Para|Aan|Til|Till'
    r'|Afzender|Ontvanger)\*{0,2}\s?:', re.IGNORECASE)
_SIG_THREAD_START = re.compile(
    r'[>*\\\s-]*(?:(?:On|Le|El|Am|Op|Den|Em|Il|W dniu)\s' + _HDR_DATE_HEAD
    + r'|Begin forwarded|Inicio del mensaje|Début du message|Anfang der weitergeleiteten'
    r'|[^\n]{0,12}(?:Forwarded|Original|Weitergeleitete|Ursprüngliche|Oorspronkelijk|transféré|reenviado)'
    r'|(?:From|Von|De|Van|Da|Från|Fra|Sent|Date|Datum|Subject|Betreff|Objet|Asunto|Onderwerp|To|An|Para|Aan)\*{0,2}\s?:)',
    re.IGNORECASE)
_DESK_SENDER = re.compile(
    r'support|customer|\bcare\b|service|\bhelp|\bteam\b|kundendienst|servicio|atenci\u00f3n|assistance|no-?reply',
    re.IGNORECASE)
_TITLE_LINE = re.compile(r'Title:[^\n]*\n?')


def _words(text):
    return len(text.split())


def _is_sentence(line):
    """ A line that reads like part of a message rather than a name, a role or an address. """
    words = _words(line)
    return words >= 8 or (words >= 3 and line.rstrip().endswith('?'))


def _signature_kind(line):
    if _SIG_DEVICE.match(line):
        return 'device'
    if _SIG_SEPARATOR.match(line):
        return 'sep'
    if line.startswith('-'):
        return 'dash'
    return 'closing'


class EmailReplyParser(object):
    """ Represents a email message that is parsed.
    """

    def __init__(self, language='en'):
        dir_path = os.path.dirname(__file__)
        with open(dir_path + "/languages_support.json", "r") as read_file:
            self.words_map = json.load(read_file)
        if language in self.words_map:
            self.language = language
        else:
            self.language = 'en'

    def read(self, text):
        """ Factory method that splits email into list of fragments
            text - A string email body
            Returns an EmailMessage instance
        """
        return EmailMessage(text, self.language, self.words_map).read()

    def parse_reply(self, text):
        """ Provides the reply portion of email.
            text - A string email body
            Returns reply body message
        """
        a = self.read(text).reply
        return a

    def find_contacts(self, text):
        """Provides a list of From To emails and the dates of these emails"""
        contacts_dict = EmailContacts(text, self.language, self.words_map).contacts()
        return contacts_dict


class EmailMessage(object):
    """ An email message represents a parsed email body.
    """

    def __init__(self, text, language, words_map):
        self.fragments = []
        self.fragment = None
        self.text = text.replace('\r\n', '\n').replace('\r', '\n')
        self.found_visible = False
        self.SIG_REGEX = None
        self.QUOTE_HDR_REGEX = None
        self.QUOTED_REGEX = None
        self.HEADER_REGEX = None
        self._MULTI_QUOTE_HDR_REGEX = None
        self.MULTI_QUOTE_HDR_REGEX = None
        self.MULTI_QUOTE_HDR_REGEX_MULTILINE = None
        self.WARNING_REGEX = None
        self.words_map = words_map
        self.language = language
        self.default_language = 'en'
        self.set_regex()

    def default_quoted_header(self):
        self.QUOTED_REGEX = re.compile(r'(>+)')
        self.HEADER_REGEX = re.compile(
            r'^[* ]*(' + self.words_map[self.language]['From']
            + '|' + self.words_map[self.language]['Sent']
            + '|' + self.words_map[self.language]['To']
            + ')\s*:[\s\n\*]*.*'
        )

    def warnings(self):
        dot = '\u200b'
        single_space = f'[ {dot}\xA0\t]'
        space = f'[,()]?{single_space}{{0,3}}[\n\r]?{single_space}{{0,3}}[,()]?'
        sentence_start = f'(?:[\n\r.!?]|^){single_space}{{0,3}}'
        # At least one of the words is required: with connectors alone ("/", "and", "or"),
        # "any update or information about ..." lost the rest of its line.
        confidential_word = '(privileged|confidential|private|sensitive)'
        confidential_variations = (
            f'{confidential_word}({space}(/|and|or|and{space}/{space}or|,)?{space}{confidential_word}){{0,2}}')
        message_variations = f'(electronic{space}|e[\-]?mail{space}|message{space}|communication{space}|transmission{space}){{1,3}}'
        self.WARNING_REGEX = re.compile(
            f'(CAUTION:|NOTICE:|Disclaimer:|Warning:|{confidential_variations}{space}Notice:|Please{space}do{space}not{space}reply'
            f'|{confidential_variations}{space}information'
            f'|{sentence_start}(The|This){space}information{space}(provided|transmitted|contained)?{space}(with)?in{space}this{space}{message_variations}'
            f'|{sentence_start}(The|This){space}information{space}(may also be|is){space}legally'
            f'|{sentence_start}(The|This){space}content[s]?{space}of{space}this{space}{message_variations}'
            f'|{sentence_start}(The|This){space}{message_variations}{space}'
            f'(may{space}contain|(and|or|and{space}/{space}or)?{space}(any|all)?{space}(files{space}transmitted|the{space}information{space}(contained|it{space}contains)|attach|associated)'
            f'|[(]?including{space}(any|all)?{space}attachments[)]?|(is|are|contains){space}{confidential_variations}'
            f'|is{space}for{space}the{space}recipients|is{space}intended{space}only|is{space}for{space}the{space}sole{space}user|has{space}been{space}scanned|with{space}its{space}contents'
            f')|{sentence_start}(The|This){space}publication,{space}copying'
            f'|{sentence_start}(The|This){space}sender{space}(cannot{space}guarantee|believes{space}that{space}this{space}{message_variations})'
            f'|{sentence_start}If{space}you{space}have{space}received{space}this{space}{message_variations}{space}in{space}error'
            f'|{sentence_start}The{space}contents{space}are{space}{confidential_variations}'
            f'|{sentence_start}(Under|According to){space}(the)?{space}(General{space}Data{space}Protection{space}Regulation|GDPR)'
            f'|{sentence_start}Click{space}here{space}to'
            f'|{sentence_start}Copyright{space}'
            f'|{sentence_start}Was{space}this{space}email{space}helpful\?'
            f'|{sentence_start}For{space}Your{space}Information:'
            f'|{sentence_start}Emails{space}are{space}not{space}secure'
            f'|{sentence_start}To make{space}sure{space}you{space}continue{space}to{space}receive'
            f'|{sentence_start}Please{space}choose{space}one{space}of{space}the{space}options{space}below'
            f'|{sentence_start}Please{space}consider{space}the{space}environment{space}before{space}printing{space}this{space}{message_variations}'
            f'|{sentence_start}This{space}e-mail{space}and{space}any{space}attachments{space}are{space}confidential'
            f')[a-zA-Z0-9:;.,?!<>()@&/\'\"\“\” {dot}\xA0\t\-]*',
            re.IGNORECASE
        )

    def nl_support(self):
        self.SIG_REGEX = re.compile(
            r'(--|__|-\w)|(^' + self.words_map[self.language]['Sent from'] + '(\w+\s*){1,3})|' \
                + "Met vriendelijke groet|Vriendelijke groet|Hartelijke groet|Met hartelijke groeten|Met groet|Groet|Groeten|Hartelijk dank|Alvast bedankt|Bedankt voor uw aandacht|Hoogachtend|Met hoogachting|In afwachting van uw reactie|In afwachting|Tot ziens|Tot snel|Tot straks|Tot later|Mvg|Vr gr|Dank bij voorbaat|Bij voorbaat dank", flags=re.IGNORECASE
        )
        self.QUOTE_HDR_REGEX = re.compile('Op.*schreef.*>:$')
        self._MULTI_QUOTE_HDR_REGEX = r'(?!Op.*Op\s.+?schreef.*>:)(Op\s(.+?)schreef.*>:)'

    def de_support(self):
        self.SIG_REGEX = re.compile(r'(--|__|-\w)|(^' + self.words_map[self.language]['Sent from'] \
            + '(\w+\s*){1,3})|' \
            + 'LB,|beste,|Mit freundlichen Grüßen|Herzliche Grüße|Beste Grüße|Mit besten Grüßen|Liebe Grüße|Viele Grüße|Mit lieben Grüßen|Schöne Grüße|Mit herzlichen Grüßen|Freundliche Grüße|Mit herzlichem Gruß|Mit bestem Gruß|Hochachtungsvoll|Mit bestem Dank im Voraus|Danke und Grüße|Freundlich grüßt|Dankeschön und liebe Grüße|Mit bestem Dank |Mit den besten Wünschen|In Erwartung Ihrer Antwort|Auf Wiedersehen|In Erwartung einer baldigen Antwort|Vielen Dank im Voraus|Mit freudigen Grüßen|In freudiger Erwartung Ihrer Antwort|Mit aufrichtigem Dank|Mit großer Hochachtung', flags=re.IGNORECASE)
        # "schrieb" as a word: "... wie geschrieben ...:" is not a header.
        self.QUOTE_HDR_REGEX = re.compile(r'[a-zA-Z]{2,5}.*\bschrieb\b.*:$')
        self._MULTI_QUOTE_HDR_REGEX = r'(?!Am.*Am\s.+?schrieb.*:)(Am\s(.+?)schrieb.*:)'

    def fr_support(self):
        self.SIG_REGEX = re.compile(
            r'(--|__|-\w)|(^' + self.words_map[self.language]['Sent from'] \
            + '(\w+\s*){1,3})|(.*(cordialement|bonne r[ée]ception|salutations'
              r'|cdlt|cdt|crdt|regards|best regard|bonne journ[ée]e))',
            re.IGNORECASE
        )
        self.QUOTE_HDR_REGEX = re.compile('Le.*a écrit.*[> ]:$')
        self._MULTI_QUOTE_HDR_REGEX = r'(?!Le.*Le\s.+?a écrit[a-zA-Z0-9.:;<>()&@ -]*:)(Le\s(.+?)a écrit[a-zA-Z0-9.:;<>()&@ -]*:)'

    def en_support(self):
        self.SIG_REGEX = re.compile(r'(--|__|-\w)|(^(sent from|get outlook)\s(\w+\s*){1,6})|(Best regards|Kind Regards|Thanks,|Thank you,|Best,|All the best|regards,)', flags=re.IGNORECASE)
        self.QUOTE_HDR_REGEX = re.compile('\s*On.*wrote\s*:$')
        self.QUOTED_REGEX = re.compile(r'(>+)|((&gt;)+)')
        self._MULTI_QUOTE_HDR_REGEX = r'(?!On.*On\s.+?wrote\s*:)(On\s(.+?)wrote\s*:)'

    def es_support(self):
        self.SIG_REGEX = re.compile(r'(--|__|-\w)|(^Enviado desde (\w+\s*){1,6})')
        self.QUOTE_HDR_REGEX = re.compile('\s*El.*escribió\s*:$')
        self._MULTI_QUOTE_HDR_REGEX = r'(?!El.*El\s.+?escribió\s*:)(El\s(.+?)escribió\s*:)'

    def ja_support(self):
        self.SIG_REGEX = re.compile(r'--|__|-\w')
        self.QUOTE_HDR_REGEX = re.compile(
            r'[0-9]*年[0-9]*月[0-9]*日[\u3000-\u303F\u3040-\u309F\u30A0-\u30FF\uFF00-\uFFEF\u4E00-\u9FAF\u2605-\u2606\u2190-\u2195\u203Ba-zA-Z0-9.:;<>()&@ -]*:?$'
        )
        self.QUOTED_REGEX = re.compile(r'(>+)|((&gt;)+)')
        self._MULTI_QUOTE_HDR_REGEX = r'(?!On.*On\s.+?wrote\s*:)(On\s(.+?)wrote\s*:)'  # Dummy multiline: doesnt work for japanese due to BeautifulSoup insreting new lines before ":" character

    def fi_support(self):
        self.SIG_REGEX = re.compile(r'(--|__|-\w)|(^Lähetetty (\w+\s*){1,3})|(^Hanki Outlook for.*)')
        self.QUOTE_HDR_REGEX = re.compile('(.+?kirjoitti(.+?kello.+?)?:)')
        self.QUOTED_REGEX = re.compile(r'(>+)|((&gt;)+)')
        # Bounded to one line: with "(.+?)" over line breaks, a text that ends with the header
        # was joined into a single header line from its first character, and the reply was empty.
        self._MULTI_QUOTE_HDR_REGEX = r'(([^\n]+?)kirjoitti[a-zA-Z0-9.:;<>()&@ -]*:$)'

    def set_regex(self):
        if hasattr(self, self.language + "_support"):
            getattr(self, self.language + "_support")()
            self.default_quoted_header()
        else:
            self.SIG_REGEX = re.compile(
                r'(--|__|-\w)|(^(' + self.words_map[self.language]['Sent from']
                + '|' + self.words_map[self.default_language]['Sent from']
                + ')(\w+\s*){1,3})'
            )
            # Grouped: with alternatives ("A|B", as for zh) the pattern matched any line that
            # contained the first word. The colon may be the full-width one.
            self.QUOTE_HDR_REGEX = re.compile('.*(?:' + self.words_map[self.language]['wrote'] + r')\s?[:\uff1a]$')
            self.default_quoted_header()
            self._MULTI_QUOTE_HDR_REGEX = r'(?!.+?' + self.words_map[self.language]['wrote'] \
                                          + '\s*:\s*)(On\s(.+?)' + self.words_map[self.language]['wrote'] + ':)'
        self.warnings()
        # Only the notice itself: the new message comes after it.
        self.FOLLOW_UP_HDR_REGEX = re.compile(r'(?<!^)This is a follow-up to your previous request[^\n]*')
        self.MULTI_QUOTE_HDR_REGEX = re.compile(self._MULTI_QUOTE_HDR_REGEX, re.DOTALL | re.MULTILINE)
        self.MULTI_QUOTE_HDR_REGEX_MULTILINE = re.compile(self._MULTI_QUOTE_HDR_REGEX, re.DOTALL)

    def read(self):
        """ Creates new fragment for each line
            and labels as a signature, quote, or hidden.
            Returns EmailMessage instance
        """
        self.text = self.text.strip()
        self.found_visible = False
        is_multi_quote_header = self.MULTI_QUOTE_HDR_REGEX_MULTILINE.search(self.text)
        if is_multi_quote_header:
            self.text = self.MULTI_QUOTE_HDR_REGEX.sub(is_multi_quote_header.groups()[0].replace('\n', ''), self.text)
        # Markdown-style helpdesk text puts the sender's address after the header's colon:
        # "On ... <a@b.c> wrote: (mailto:a@b.c)" or, with the address already removed,
        # "wrote: [](mailto:)". The header patterns need the line to end at the colon. Only
        # a line that is a quote header without the tail loses it ("Email: [](mailto:)" stays).
        if 'mailto:' in self.text:
            self.text = MAILTO_TAIL_REGEX.sub(self._strip_header_mailto, self.text)
        self.text = self.FOLLOW_UP_HDR_REGEX.sub('', self.text)
        # Fix any outlook style replies, with the reply immediately above the signature boundary line
        #   See email_2_2.txt for an example
        self.text = re.sub('([^\n])(?=\n ?[_-]{7,})', '\\1\n', self.text, re.MULTILINE)

        self.text = re.sub(self.WARNING_REGEX, '\n', self.text)
        self.lines, self.inline_headers, self.forced_headers = _split_inline_headers(self.text.split('\n'))
        self.lines.reverse()

        for line in self.lines:
            if line.strip():
                self._scan_line(line.strip())

        self._finish_fragment()
        self.fragments.reverse()
        self._review_signatures()

        return self

    def _review_signatures(self):
        """ Un-marks signature fragments that would take the customer's text with them:
            - no visible text above the marker: it is not a signature;
            - a closing ("Thanks,", "Cordialement") only when the line is just the closing,
              optionally with a name, and what follows is short and not sentence-like;
            - "-word" only as a short sign-off ("-John");
            - a device line ("Sent from my iPhone") removes only its own line;
            - a signature never takes a sentence-like tail several times the size of the
              text above it.
        """
        above = 0
        reviewed = []
        for position, fragment in enumerate(self.fragments):
            content = fragment.content
            if position == 0:
                content = _TITLE_LINE.sub('', content, 1) if content.startswith('Title:') else content
            if not fragment.signature or fragment.hidden_by_header:
                if not (fragment.hidden or fragment.quoted or fragment.headers or fragment.signature):
                    above += len(content.strip())
                reviewed.append(fragment)
                continue
            lines = fragment.content.split('\n')
            first, tail = lines[0].strip(), [line for line in lines[1:] if line.strip()]
            kind = _signature_kind(first)
            if kind == 'device':
                # Only the device line itself is a signature when the message continues
                # below it. With text above it, what follows must read like a message and
                # not start a quoted thread; otherwise it stays hidden with the line.
                if above > 0 and (not any(_is_sentence(line) for line in tail)
                                  or _SIG_THREAD_START.match(tail[0])
                                  or _find_inline_header(tail[0]) is not None):
                    reviewed.append(fragment)
                    continue
                rest = Fragment(False, '')
                rest.lines = list(reversed(tail))
                rest.finish()
                fragment._content = first
                reviewed.append(fragment)
                if tail:
                    above += len(rest.content)
                    reviewed.append(rest)
                continue
            keep = above > 0
            if kind == 'sep':
                if first.strip('-_ \t'):
                    # "----- Forwarded message -----", "-----Original Message-----": a thread
                    # marker, not a signature line; what follows is the thread.
                    keep = True
                elif any(_SIG_THREAD_LABEL.match(line) or _find_inline_header(line) for line in tail[:3]):
                    keep = True
                elif keep:
                    # A rule between two parts of the customer's text, or above a form's
                    # details, looks the same as one above a signature: only a short tail
                    # without sentences is taken as a signature.
                    keep = len(tail) <= 10 and not any(_is_sentence(line) for line in tail)
            if keep and kind == 'dash':
                # "-John" closes a message; "-item" lines followed by more text are a list.
                later_text = any(
                    not (later.quoted or later.headers or later.hidden_by_header)
                    and (not later.signature or _signature_kind(later.content.split('\n')[0].strip()) == 'dash')
                    for later in self.fragments[position + 1:])
                keep = not later_text and _words(first) <= 4 and not re.search(r'[?!:]', first) \
                    and len(tail) <= 4 and not any(_is_sentence(line) for line in tail)
            if keep and kind == 'closing':
                match = self.SIG_REGEX.match(first)
                rest_of_line = first[match.end():].strip(' ,.!-') if match else ''
                keep = _words(first) <= 8 and _words(rest_of_line) <= 4 and '?' not in first \
                    and not _SIG_CONTINUES.match(rest_of_line) \
                    and not any(_is_sentence(line) for line in tail[:1])
            if not keep:
                # The text comes back, but not a quoted thread that follows it in the same
                # fragment ("... / ----- Forwarded Message ----- / From: ...").
                thread = next((index for index, line in enumerate(lines)
                               if index and (_SIG_THREAD_START.match(line.strip())
                                             or _find_inline_header(line) is not None)), None)
                if thread is not None:
                    rest = Fragment(False, '')
                    rest.lines = list(reversed(lines[thread:]))
                    rest.finish()
                    rest.signature = rest.hidden = True
                    fragment._content = '\n'.join(lines[:thread])
                    content = fragment._content
                fragment.signature = False
                fragment.hidden = False
                above += len(content.strip())
                reviewed.append(fragment)
                if thread is not None:
                    reviewed.append(rest)
                continue
            reviewed.append(fragment)
        self.fragments = reviewed

    def _strip_header_mailto(self, match):
        line_start = self.text.rfind('\n', 0, match.start()) + 1
        line = self.text[line_start:match.start() + 1]
        if not self.text[:line_start].strip():
            # A header that opens the message is left as it is (see _split_inline_headers).
            return match.group(0)
        if self.QUOTE_HDR_REGEX.match(line.strip()):
            return match.group(1)
        return match.group(0)

    @property
    def reply(self):
        """ Captures reply message within email
        """
        reply = []
        for f in self.fragments:
            if not (f.hidden or f.quoted or f.signature):
                reply.append(f.content)
        reply = '\n'.join(reply)
        if not self._has_body(reply):
            rescued = self._rescue()
            if rescued:
                reply = (reply + '\n' + rescued).strip()
        return reply

    @staticmethod
    def _has_body(text):
        """ False when text is empty or only a "Title: ..." line, thread markers and rules. """
        text = _TITLE_LINE.sub('', text.strip(), 1) if text.strip().startswith('Title:') else text
        for line in text.split('\n'):
            line = line.strip()
            if line and line.strip('-_ \t\\*') and not _HDR_FORWARD_MARKER.search(line) \
                    and not _SIG_THREAD_START.match(line) \
                    and not (_SIG_DEVICE.match(line) and _words(line) <= 8):
                return True
        return False

    def _rescue(self):
        """ Last resort when nothing of the message would be returned.
            A: text that only the signature rules removed (not quoted, not under a header).
            B: otherwise the first quoted message - the text under the first header, or the
               quoted lines when there is no header - unquoted one level, up to the next
               header or deeper quote. An empty reply above a quote, a forward without a note
               and a message that quotes itself all look the same here; keeping the text is
               preferred over returning nothing.
        """
        kept = [f.content for f in self.fragments
                if not (f.quoted or f.headers or f.hidden_by_header) and f.content.strip()]
        kept = '\n'.join(kept)
        if self._has_body(kept) and len(_TITLE_LINE.sub('', kept, 1).strip()) >= 20:
            self.rescued = 'A'
            return '\n'.join(f.content for f in self.fragments
                             if (f.hidden or f.signature) and not (f.quoted or f.headers or f.hidden_by_header)
                             and self._has_body(f.content))
        start = next((index for index, f in enumerate(self.fragments) if f.headers or f.quoted), None)
        if start is None:
            return ''
        lines = []
        for fragment in self.fragments[start:]:
            for line in fragment.content.split('\n'):
                line = line.strip()
                if line.startswith('>'):
                    line = line[1:].strip()
                if line.startswith('>'):
                    if lines:
                        return self._rescued_text(lines)
                    continue
                if not line.strip('-_ \t\\*'):
                    continue
                if self.QUOTE_HDR_REGEX.match(line) or self.HEADER_REGEX.match(line) \
                        or line in self.inline_headers or _SIG_THREAD_START.match(line) \
                        or _SIG_THREAD_LABEL.match(line) or _find_inline_header(line) is not None:
                    if lines:
                        return self._rescued_text(lines)
                    if _DESK_SENDER.search(line):
                        # Quoted from a support desk: an empty reply above the shop's own
                        # message. Returning that as the customer's text is worse than nothing.
                        return ''
                    continue
                lines.append(line)
        return self._rescued_text(lines)

    def _rescued_text(self, lines):
        text = '\n'.join(lines)
        if len(text.strip()) < 20:
            return ''
        self.rescued = 'B'
        return text

    def _scan_line(self, line):
        """ Reviews each line in email message and determines fragment type
            line - a row of text from an email message
        """
        # A forced header (see _split_inline_headers) always starts a headers fragment, which
        # hides everything below it, even when the next line is a quoted (">") one.
        is_forced_header = line in self.forced_headers
        is_quote_header = self.QUOTE_HDR_REGEX.match(line) is not None or line in self.inline_headers
        is_quoted = self.QUOTED_REGEX.match(line) is not None
        is_header = is_quote_header or self.HEADER_REGEX.match(line) is not None

        if self.fragment and self.SIG_REGEX.match(self.fragment.lines[-1].strip()):
            self.fragment.signature = True
            self._finish_fragment()
        if self.fragment \
                and ((self.fragment.headers == is_header and self.fragment.quoted == is_quoted) or
                     (self.fragment.quoted and not is_forced_header
                      and (is_quote_header or len(line.strip()) == 0))):
            self.fragment.lines.append(line)
        else:
            self._finish_fragment()
            self.fragment = Fragment(is_quoted, line, headers=is_header)

    def _finish_fragment(self):
        """ Creates fragment
        """

        if self.fragment:
            self.fragment.finish()
            if self.fragment.headers:
                # Regardless of what's been seen to this point, if we encounter a headers fragment,
                # all the previous fragments should be marked hidden and found_visible set to False.
                self.found_visible = False
                for f in self.fragments:
                    f.hidden = True
                    f.hidden_by_header = True
            if not self.found_visible:
                if self.fragment.quoted \
                        or self.fragment.headers \
                        or self.fragment.signature \
                        or (len(self.fragment.content.strip()) == 0):

                    self.fragment.hidden = True
                else:
                    self.found_visible = True
            self.fragments.append(self.fragment)
        self.fragment = None


class EmailContacts(EmailMessage):

    def contacts(self):
        self.text = self.text.strip()
        HEADER_BLOCK = re.compile(
            r'('
            + '[>* ]*' + self.words_map[self.language]['From'] + '[ ]*:(.*)\n'
            + '[>* ]*(?:' + self.words_map[self.language]['Sent'] + '|Date)[ ]*:(.*)\n'
            + '[>* ]*' + self.words_map[self.language]['To'] + '[ ]*:(.*)\n'
            + ')'
        )
        EMAIL = re.compile(r'([a-zA-Z0-9_\-\.]+@[a-zA-Z0-9_\-\.]+\.[a-zA-Z]{2,5})')
        headers = HEADER_BLOCK.findall(self.text)
        json = []
        for header in headers:
            contact = {'from': '', 'to': '', 'date': ''}
            from_email = EMAIL.search(header[1])
            if from_email:
                contact['from'] = from_email.groups()[0]
            contact['date'] = header[2]
            to_email = EMAIL.search(header[3])
            if to_email:
                contact['to'] = to_email.groups()[0]
            json.append(contact)
        return json


class Fragment(object):
    """ A Fragment is a part of
        an Email Message, labeling each part.
    """

    def __init__(self, quoted, first_line, headers=False):
        self.signature = False
        self.headers = headers
        self.hidden = False
        self.hidden_by_header = False
        self.quoted = quoted
        self._content = None
        self.lines = [first_line]

    def finish(self):
        """ Creates block of content with lines
            belonging to fragment.
        """
        self.lines.reverse()
        self._content = '\n'.join(self.lines)
        self.lines = None

    @property
    def content(self):
        return self._content.strip()
