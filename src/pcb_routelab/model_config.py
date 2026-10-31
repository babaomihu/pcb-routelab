"""Opt-in Anthropic-compatible provider; no persistent credential copies."""
import os
from urllib.parse import urlsplit


def provider():
    if os.environ.get('PCB_ROUTELAB_ENABLE_MODEL')!='1' or os.environ.get('PCB_ROUTELAB_OFFLINE')=='1':
        raise RuntimeError('Model networking is disabled; no request sent')
    result={k:os.environ.get('PCB_ROUTELAB_'+v,'') for k,v in
            [('api_key','API_KEY'),('base_url','BASE_URL'),('model','MODEL')]}
    if not all(result.values()):raise ValueError('Set PCB_ROUTELAB_API_KEY, BASE_URL and MODEL')
    url=urlsplit(result['base_url'])
    if url.scheme!='https' or not url.hostname or url.username or url.password or url.query or url.fragment:
        raise ValueError('Provider must be an HTTPS base URL without embedded credentials/query')
    return result
