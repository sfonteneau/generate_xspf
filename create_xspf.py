import glob
import os
from urllib.parse import quote  
from jinja2 import Template
import xml.etree.ElementTree as ET

import requests

url_dl= 'https://myurl/secret1'

list_url_sup=['https://urlfriends/secret2/vlc.xspf']

folder='/downloads'

list_ok=["3g2", "3gp", "3gp2", "3gpp", "amv", "asf", "avi", "bik", "crf", "dav", "divx", "drc", "dv", "dvr-ms" ,"evo", "f4v", "flv", "gvi", "gxf", "iso","m1v", "m2v", "m2t", "m2ts", "m4v", "mkv", "mov","mp2", "mp2v", "mp4", "mp4v", "mpe", "mpeg", "mpeg1", "mpeg2", "mpeg4", "mpg", "mpv2", "mts", "mtv", "mxf", "mxg", "nsv", "nuv","ogg", "ogm", "ogv", "ogx", "ps", "rec", "rm", "rmvb", "rpl", "thp", "tod", "ts", "tts", "txd", "vob", "vro", "webm", "wm", "wmv", "wtv", "xesc"]


def fetch_xspf(url):
    response = requests.get(url,verify=False)
    response.raise_for_status()
    return response.text


def parse_xspf(xml_content):
    root = ET.fromstring(xml_content)
    namespace = {'xspf': 'http://xspf.org/ns/0/'}  
    
    tracks = []
    for track in root.findall(".//xspf:track", namespace):
        title_elem = track.find("xspf:title", namespace)
        location_elem = track.find("xspf:location", namespace)
        title = title_elem.text if title_elem is not None else "Unknown Title"
        location = location_elem.text if location_elem is not None else "Unknown Location"
        
        tracks.append({"title": title, "location": location})
    
    return tracks

template = r"""<?xml version="1.0" encoding="UTF-8"?>
<playlist xmlns="http://xspf.org/ns/0/" xmlns:vlc="http://www.videolan.org/vlc/playlist/ns/0/" version="1">
        <title>Liste de lecture</title>
        <trackList>
                {% for entry in dict_filename %}
                <track>
                        <title>{{ dict_filename[entry]['title']  }}</title>
                        <location>{{ dict_filename[entry]['urldl'] }}</location>
                        <extension application="http://www.videolan.org/vlc/playlist/0">
                                <vlc:id>{{dict_filename[entry]['nb']}}</vlc:id>
                                <vlc:option>network-caching=2000</vlc:option>
                        </extension>
                </track>{% endfor %}
        </trackList>
        <extension application="http://www.videolan.org/vlc/playlist/0">
                {% for entry in dict_filename %}
                <vlc:item tid="{{dict_filename[entry]['nb']}}"/>{% endfor %}
        </extension>
</playlist>
""" 
template_index = r"""
<ul>
  {% for entry in dict_filename %}
  <li><a href="{{ dict_filename[entry]['urldl'] }}">{{ dict_filename[entry]['title']  }}</a></li>
  {% endfor %}
</ul> 
""" 

dict_filename = {}
nb = 0

for f in sorted(glob.glob('/downloads/**' ,recursive=True)):

    if os.path.isdir(f):
        continue
    if not f.split('.')[-1].lower() in list_ok:
        continue

    d = f[len(folder):]

    if len(d.split('/')) > 1:
        filename = d.rsplit('/')[-1]
        path = '/' + d.rsplit('/',1)[0]
    else:
        filename = d
        path= '/'

    title = filename.rsplit('.',1)[0].replace('.',' ').replace('_',' ').replace('&','&#38;').replace('<','&#60;').replace('>','&#62;').replace("'",'&#39;').replace('"','&#34;')

    dict_filename[title]= {"title":title,"urldl":url_dl + quote(d),"nb":str(nb)}

    nb = nb + 1

for url in list_url_sup:
    try:
        xml_content = fetch_xspf(url)

        tracks = parse_xspf(xml_content)
        for track in tracks:
            if track['title'] in dict_filename:
                continue
            title = track['title'].rsplit('.',1)[0].replace('.',' ').replace('_',' ').replace('&','&#38;').replace('<','&#60;').replace('>','&#62;').replace("'",'&#39;').replace('"','&#34;')
            dict_filename[title]= {"title":title,"urldl":track['location'],"nb":str(nb)}
            nb = nb + 1
    except:
        pass
    
ftest = Template(template)
datafinal = ftest.render(dict_filename=dict_filename)
with open('%s/vlc.xspf' % folder,"w") as f:
    f.write(datafinal)

newdict = {}
newdict['Playlist VLC'] = {'title':'Playlist VLC','urldl':url_dl + '/vlc.xspf'}
newdict.update(dict_filename)
ftest = Template(template_index)
datafinal = ftest.render(dict_filename=newdict)
with open('%s/index.html' % folder,"w") as f:
    f.write(datafinal)
