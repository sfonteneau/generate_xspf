import glob
import os
from urllib.parse import quote  
from jinja2 import Template

url_nextcloud = r"https://nextcloud.mydomain.lan/s/123456/download"
folder='/downloads'

template = r"""<?xml version="1.0" encoding="UTF-8"?>
<playlist xmlns="http://xspf.org/ns/0/" xmlns:vlc="http://www.videolan.org/vlc/playlist/ns/0/" version="1">
        <title>Liste de lecture</title>
        <trackList>
                {% for entry in dict_filename %}
                <track>
                        <title>{{ dict_filename[entry]['title']  }}</title>
                        <location>{{ url_nextcloud }}?path={{dict_filename[entry]['path']}}&amp;files={{dict_filename[entry]['filename']}}</location>
                        <extension application="http://www.videolan.org/vlc/playlist/0">
                                <vlc:id>{{dict_filename[entry]['nb']}}</vlc:id>
                                <vlc:option>network-caching=120000</vlc:option>
                        </extension>
                </track>{% endfor %}
        </trackList>
        <extension application="http://www.videolan.org/vlc/playlist/0">
                {% for entry in dict_filename %}
                <vlc:item tid="{{dict_filename[entry]['nb']}}"/>{% endfor %}
        </extension>
</playlist>
"""

dict_filename = {}
nb = 0
for f in sorted(glob.glob('%s/**' % folder,recursive=True), key=os.path.getmtime,reverse=True):
    d = f.split('/',2)[-1]
    if f.endswith(".xspf"):
        continue
    if os.path.isdir(f):
        continue
    if len(d.split('/')) > 1:
        filename = d.rsplit('/')[-1]
        path = '/' + d.rsplit('/',1)[0]
    else:
        filename = d
        path= '/'
    title = filename.rsplit('.',1)[0].replace('.',' ').replace('_',' ')
    dict_filename[title]= {"title":title,"filename":quote(filename),"path":quote(path).replace('/',r'%2F'),"nb":str(nb)}
    nb = nb + 1

ftest = Template(template)
datafinal = ftest.render(dict_filename=dict_filename,url_nextcloud=url_nextcloud)

with open('%s/vlc.xspf' % folder,"w") as f:
    f.write(datafinal)
