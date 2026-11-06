"""Public-information prompts and strict JSON parsing, fixed before inference."""
import json

SCHEMA = ('Artist(ArtistId,Name); Album(AlbumId,Title,ArtistId); '
          'Genre(GenreId,Name); Track(TrackId,Name,AlbumId,GenreId,Milliseconds); '
          'Invoice(InvoiceId,BillingCountry,Total).')


def prompt(task, stage, observation=None):
    question = task['question']+'\nRequired answer format: '+task['answer_format']+'.'
    if task['family'] == 'sqlite_query':
        question += '\nPublic SQLite schema: '+SCHEMA
    if stage == 'plan':
        tool = ('Return only a JSON object with exactly one key "query" whose value is one read-only SQLite SELECT statement.'
                if task['family'] == 'sqlite_query' else
                'Return only a JSON object for a source search, either {"needle":"literal search text"} or {"start_line":1,"line_count":20}.')
        return question+'\nYou may make exactly one tool call on the pinned source. '+tool
    if stage not in ('direct', 'answer'):
        raise ValueError('Unknown prompt stage')
    if observation is not None:
        question += '\nActual tool observation:\n'+json.dumps(observation, sort_keys=True, allow_nan=False)
    return question+'\nReturn only the requested JSON answer. Do not include Markdown, prose or a tool call.'


def parse(text):
    if not isinstance(text, str):
        raise ValueError('No model text')
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('Duplicate JSON key')
            result[key] = value
        return result
    return json.loads(text, object_pairs_hook=pairs,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Nonfinite JSON')))


def legal_payload(task, value):
    if not isinstance(value, dict):
        return False
    if task['family'] == 'sqlite_query':
        return set(value) == {'query'} and isinstance(value['query'], str) and 1 <= len(value['query']) <= 4000
    if set(value) == {'needle'}:
        return isinstance(value['needle'], str) and 1 <= len(value['needle']) <= 128
    return (set(value) == {'start_line', 'line_count'} and type(value['start_line']) is int
            and type(value['line_count']) is int and value['start_line'] >= 1 and 1 <= value['line_count'] <= 120)
