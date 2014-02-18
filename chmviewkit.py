# -*- coding: UTF-8 -*-
# -*- Mode: Python; py-indent-offset: 4 -*-
"""
CHM View Kit - chm viewer based on gtk webkit libraries

Copyright © 2011, Ojuba Team <core@ojuba.org>

        Released under terms of Waqf Public License.
        This program is free software; you can redistribute it and/or modify
        it under the terms of the latest version Waqf Public License as
        published by Ojuba.org.

        This program is distributed in the hope that it will be useful,
        but WITHOUT ANY WARRANTY; without even the implied warranty of
        MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.

        The Latest version of the license can be found on
        "http://waqf.ojuba.org/license"

"""
import sys, os, os.path, time, re, sqlite3, hashlib

import shutil, tempfile
import threading, socket
import gettext
from gi.repository import GObject
from gi.repository import Gtk, Gdk, Pango
from gi.repository import WebKit
from subprocess import Popen, PIPE
from urllib import unquote
from urlparse import urlparse, urlsplit
from htmlentitydefs import entitydefs

from paste import httpserver
from chm import chm, chmlib

def async_gtk_call(f):
    def worker((function, args, kwargs)):
        function(*args, **kwargs)
    def f2(*args, **kwargs):
        GObject.idle_add(worker, (f, args, kwargs))
    return f2

setsid = getattr(os, 'setsid', None)
if not setsid: setsid = getattr(os, 'setpgrp', None)
_ps = []

def run_in_bg(cmd):
    global _ps
    setsid = getattr(os, 'setsid', None)
    if not setsid: setsid = getattr(os, 'setpgrp', None)
    _ps = filter(lambda x: x.poll() != None, _ps) # remove terminated processes from _ps list
    _ps.append(Popen(cmd, 0, '/bin/sh', shell = True, preexec_fn = setsid))


def get_exec_full_path(fn):
    a = filter(lambda p: os.access(p, os.X_OK),
             map(lambda p: os.path.join(p, fn),
                 os.environ['PATH'].split(os.pathsep)))
    if a: return a[0]
    return None


def guess_browser():
    e = get_exec_full_path("xdg-open")
    if not e:
        e = get_exec_full_path("firefox")
    if not e:
        e = "start"
    return e

broswer = guess_browser()

def sure(msg, w = None):
    dlg = Gtk.MessageDialog(w,
                            Gtk.DialogFlags.MODAL,
                            Gtk.MessageType.QUESTION,
                            Gtk.ButtonsType.YES_NO, msg)
    dlg.connect("response", lambda *args: dlg.hide())
    r = dlg.run()
    dlg.destroy()
    return r == Gtk.ResponseType.YES

def error(msg, w=None):
    dlg = Gtk.MessageDialog(w,
                            Gtk.DialogFlags.MODAL,
                            Gtk.MessageType.ERROR,
                            Gtk.ButtonsType.OK, msg)
    dlg.connect("response", lambda *args: dlg.hide())
    r = dlg.run()
    dlg.destroy()
    return r == Gtk.ResponseType.OK

class WV(WebKit.WebView):
    def __init__(self, key):
        WebKit.WebView.__init__(self)
        self._lock = threading.Lock()
        self.key = key
        self.links_prompt = True
        #self.set_view_source_mode(True)
        self.set_full_content_zoom(True)
        self.connect_after("populate-popup", self.populate_popup)
        self.connect("navigation-requested", self._navigation_requested_cb)
        #self.connect("navigation-policy-decision-requested", self._navigation_policy_cb)

    def _navigation_policy_cb(self, view, frame, networkRequest, action, policy, *a, **kw):
        uri = networkRequest.get_uri()
        u = urlparse(uri)
        if u.scheme != 'file' and u.hostname != '127.0.0.1' and u.hostname != 'localhost':
            policy.ignore()
            if view.links_prompt and not sure(_("open [%s] in external browser") % uri, None):
                return True
            run_in_bg("%s '%s'" % (broswer ,uri))
            return True
        return False

    def _navigation_requested_cb(self, view, frame, networkRequest):
        uri = networkRequest.get_uri()
        u = urlparse(uri)
        if u.scheme != 'file' and u.hostname != '127.0.0.1' and u.hostname != 'localhost':
            if view.links_prompt and not sure(_("open [%s] in external browser") % uri, None):
                return 1
            run_in_bg("%s '%s'" % (broswer ,uri))
            return 1
        return 0

    def eval_js(self, e):
         """
         can be used to eval a javascript expression
         eg. to obtain value of a javascript variable given its name
         """
         self._lock.acquire()
         self.execute_script('$_eval_js_old_title=document.title;document.title=%s;' % e)
         r = self.get_main_frame().get_title()
         self.execute_script('document.title=$_eval_js_old_title;')
         self._lock.release()
         return r


    def populate_popup(self, view, menu):
        menu.append(Gtk.SeparatorMenuItem.new())
        i = Gtk.ImageMenuItem.new_from_stock(Gtk.STOCK_ZOOM_IN, None)
        i.connect('activate', lambda m,v,*a,**k: v.zoom_in(), view)
        i.set_always_show_image(True)
        menu.append(i)
        i = Gtk.ImageMenuItem.new_from_stock(Gtk.STOCK_ZOOM_OUT, None)
        i.connect('activate', lambda m,v,**k: v.zoom_out(), view)
        i.set_always_show_image(True)
        menu.append(i)
        i = Gtk.ImageMenuItem.new_from_stock(Gtk.STOCK_ZOOM_100, None)
        i.set_always_show_image(True)
        i.connect('activate', lambda m,v,*a,**k: v.get_zoom_level() == 1.0 or v.set_zoom_level(1.0), view)
        menu.append(i)

        menu.show_all()
        return False

class TabLabel (Gtk.HBox):
    """A class for Tab labels"""

    __gsignals__ = {
            "close": (GObject.SIGNAL_RUN_FIRST,
                                GObject.TYPE_NONE,
                                (GObject.TYPE_OBJECT,))
            }

    def __init__ (self, title, child):
        """initialize the tab label"""
        Gtk.HBox.__init__(self)
        self.title = title
        self.child = child
        self.label = Gtk.Label(title)
        self.label.props.max_width_chars = 30
        self.label.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
        self.label.set_alignment(0.0, 0.5)
        # FIXME: use another icon
        icon = Gtk.Image.new_from_icon_name("chmviewkit", Gtk.IconSize.MENU)
        close_image = Gtk.Image.new_from_stock(Gtk.STOCK_CLOSE, Gtk.IconSize.MENU)
        close_button = Gtk.Button()
        close_button.set_relief(Gtk.ReliefStyle.NONE)
        close_button.connect("clicked", self._close_tab, child)
        close_button.add(close_image)
        self.pack_start(icon, False, False, 0)
        self.pack_start(self.label, True, True, 0)
        self.pack_start(close_button, False, False, 0)

        self.set_data("label", self.label)
        self.set_data("close-button", close_button)
        self.connect("style-set", tab_label_style_set_cb)

    def set_label_text (self, text):
        """sets the text of this label"""
        if text: self.label.set_label(text)

    def _close_tab (self, widget, child):
        self.emit("close", child)

def tab_label_style_set_cb(tab_label, style):
    context = tab_label.get_pango_context()
    # FIXME: AttributeError: 'function' object has no attribute 'font_desc'
    font_desc = Pango.font_description_from_string(tab_label.label.get_label())
    metrics = context.get_metrics(font_desc, context.get_language())
    char_width = metrics.get_approximate_digit_width()
    (Bool, width, height) = Gtk.icon_size_lookup_for_settings(tab_label.get_settings(),
                                                              Gtk.IconSize.MENU)
    #tab_label.set_size_request(20 * Pango.PIXELS(char_width) + 2 * width, -1)
    tab_label.set_size_request(20 * char_width + 2 * width, -1)
    button = tab_label.get_data("close-button")
    button.set_size_request(width + 4, height + 4)

class ContentPane (Gtk.HPaned):
    __gsignals__ = {
        "focus-view-title-changed": (GObject.SIGNAL_RUN_FIRST,
                                     GObject.TYPE_NONE,
                                     (GObject.TYPE_OBJECT,
                                      GObject.TYPE_STRING,)),
        "focus-view-load-committed": (GObject.SIGNAL_RUN_FIRST,
                                      GObject.TYPE_NONE,
                                      (GObject.TYPE_OBJECT,
                                       GObject.TYPE_OBJECT,)),
        "new-window-requested": (GObject.SIGNAL_RUN_FIRST,
                                 GObject.TYPE_NONE,
                                 (GObject.TYPE_OBJECT,))
        }

    def __init__ (self,
                  win, 
                  default_url = None, 
                  default_title = None,
                  hp = Gtk.PolicyType.NEVER,
                  vp = Gtk.PolicyType.AUTOMATIC):
        """initialize the content pane"""
        Gtk.HPaned.__init__(self)
        self.win = win
        self.tabs = Gtk.Notebook()
        self.sidepane = Gtk.Notebook()
        self.add1(self.sidepane)
        self.add2(self.tabs)
        self.sidepane.set_show_tabs(False)
        self.tabs.set_scrollable(True)
        self.default_url = default_url
        self.default_title = default_title
        self.hp = hp
        self.vp = vp
        self.tabs.props.scrollable = True
        #self.tabs.props.homogeneous = True
        self.tabs.connect("switch-page", self._switch_page)

        self.show_all()
        self._hovered_uri = None

    def load (self, uri):
        """load the given uri in the current web view"""
        child = self.tabs.get_nth_page(self.tabs.get_current_page())
        wv = child.get_child()
        wv.open(uri)

    def new_tab_with_webview (self, webview):
        """creates a new tab with the given webview as its child"""
        self.tabs._construct_tab_view(webview)

    def new_tab (self, url = None, key = None):
        """creates a new page in a new tab"""
        # create the tab content
        wv = WV(key)
        #if url: wv.open(url)
        self._construct_tab_view(wv, url)
        return wv

    def _update_buttons(self, view):
        self.win.go_back_b.set_sensitive(view.can_go_back())
        self.win.go_forward_b.set_sensitive(view.can_go_forward())

    def _construct_tab_view (self, wv, url=None, title=None):
        wv.connect("hovering-over-link", self._hovering_over_link_cb)
        wv.connect("populate-popup", self._populate_page_popup_cb)
        wv.connect("load-committed", self._view_load_committed_cb)
        wv.connect("load-finished", self._view_load_finished_cb)
        wv.connect("create-web-view", self._new_web_view_request_cb)

        # load the content
        self._hovered_uri = None
        if not url: url = self.default_url
        else: wv.open(url)
        #elif url!=wv.get_property("uri"): wv.open(url)

        scrolled_window = Gtk.ScrolledWindow()
        scrolled_window.props.hscrollbar_policy = self.hp
        scrolled_window.props.vscrollbar_policy = self.vp
        scrolled_window.add(wv)
        scrolled_window.show_all()

        # create the tab
        if not title: title = self.default_title
        if not title: title = url
        label = TabLabel(title, scrolled_window)
        label.connect("close", self._close_tab)
        label.show_all()

        new_tab_number = self.tabs.append_page(scrolled_window, label)
        self.tabs.set_tab_reorderable(scrolled_window, True)
        #self.tabs.set_tab_label_packing(scrolled_window, False, False, Gtk.PackType.START)
        self.tabs.set_tab_label(scrolled_window, label)

        # hide the tab if there's only one
        self.tabs.set_show_tabs(self.tabs.get_n_pages() > 1)

        self.show_all()
        self.tabs.set_current_page(new_tab_number)

    def _populate_page_popup_cb(self, view, menu):
        # misc
        if self._hovered_uri:
            open_in_new_tab = Gtk.MenuItem(_("Open Link in New Tab"))
            open_in_new_tab.connect("activate", self._open_in_new_tab, view)
            menu.insert(open_in_new_tab, 0)
            menu.show_all()

    def _open_in_new_tab (self, menuitem, view):
        self.new_tab(self._hovered_uri, key=view.key)

    def _close_tab (self, label, child):
        page_num = self.tabs.page_num(child)
        if page_num != -1:
            view = child.get_child()
            view.destroy()
            self.tabs.remove_page(page_num)
        self.tabs.set_show_tabs(self.tabs.get_n_pages() > 1)

    def _switch_page (self, notebook, page, page_num):
        child = self.tabs.get_nth_page(page_num)
        view = child.get_child()
        frame = view.get_main_frame()
        self.emit("focus-view-load-committed", view, frame)
        key = view.key
        if key and self.win.app.chm[key].has_key("pane"):
            n = self.sidepane.page_num(self.win.app.chm[key]["pane"])
            if n >= 0: self.sidepane.set_current_page(n)
        self._update_buttons(view)

    def _hovering_over_link_cb (self, view, title, uri):
        self._hovered_uri = uri

    def _view_load_committed_cb (self, view, frame):
        self.emit("focus-view-load-committed", view, frame)
        self._update_buttons(view)
        self._update_sidepan(frame)
            
    def _update_sidepan_old(self, frame):
        # FIXME: use other method to do this 
        ## This function not used anymore!!
        '''Update sidpan according to frame url'''
        l=frame.get_uri().split('/', 3)
        if len(l)!=4: return
        l=l[3].split('$/', 1)
        if len(l)!=2: return
        key,sub_uri = l
        def checkLine(model, path, i, tree):
            if sub_uri == store.get_value(i,2):
                tree.expand_to_path(path)
                tree.scroll_to_cell(path)
                tree.get_selection().select_iter(i)
                return True
        pane = self.win.app.chm[key]["pane"]
        pane.working = True
        for t in (pane.tree, pane.ix, pane.results):
            store = t.get_model()
            store.foreach(checkLine, t)
        pane.working = False
        
    def _update_sidepan(self, frame):
        '''Update sidpan according to frame url'''
        l=frame.get_uri().split('/', 3)
        if len(l) != 4: return
        l = l[3].split('$/', 1)
        if len(l) != 2: return
        key,sub_uri = l
        pane = self.win.app.chm[key]["pane"]
        pane.working = True
        for t, c in ((pane.tree, pane.tree_cont),
                     (pane.results, pane.result_cont),
                     (pane.ix, pane.ix_cont)):
            sel=t.get_selection()
            sel.unselect_all()
            if c.has_key(sub_uri):
                p, i = c[sub_uri]
                t.expand_to_path(p)
                t.scroll_to_cell(p)
                sel.select_iter(i)
        pane.working = False

    def _view_load_finished_cb(self, view, frame):
        child = self.tabs.get_nth_page(self.tabs.get_current_page())
        label = self.tabs.get_tab_label(child)
        title = frame.get_title()
        if not title:
            title = frame.get_uri()
        label.set_label_text(title)
        self.win._do_highlight(self.win.search_e.get_text())

    def _new_web_view_request_cb (self, web_view, web_frame):
        view = self.new_tab(key = web_view.key)
        view.connect("web-view-ready", self._new_web_view_ready_cb)
        return view

    def _new_web_view_ready_cb (self, web_view):
        self.emit("new-window-requested", web_view)

normalize_tb={
65: 97, 66: 98, 67: 99, 68: 100, 69: 101, 70: 102, 71: 103, 72: 104, 73: 105, 74: 106, 75: 107, 76: 108, 77: 109, 78: 110, 79: 111, 80: 112, 81: 113, 82: 114, 83: 115, 84: 116, 85: 117, 86: 118, 87: 119, 88: 120, 89: 121, 90: 122,
1600: None, 1569: 1575, 1570: 1575, 1571: 1575, 1572: 1575, 1573: 1575, 1574: 1575, 1577: 1607, 1611: None, 1612: None, 1613: None, 1614: None, 1615: None, 1616: None, 1617: None, 1618: None, 1609: 1575}

def normalize(s):
    return s.translate(normalize_tb)

def _build_entiries_re():
    p=[]
    for k,v in entitydefs.items():
        if v.startswith('&'): continue
        p.append(re.escape(k))
    return re.compile("&(%s);" % "|".join(p), re.I)

_entities_re = _build_entiries_re()

def _fix_entities(s):
    if not s: return ""
    return _entities_re.sub(lambda m: entitydefs.get(m.group(1), m.group(1)), s)

class BookSidePane(Gtk.Notebook):
    def __init__(self, win, app, key):
        Gtk.Notebook.__init__(self)
        self.working = False
        self.win = win
        self.app = app
        self.key = key
        self.tree_cont = {}
        self.result_cont = {}
        self.ix_cont = {}
        self.append_page(self.build_toc_tree(), Gtk.Label(_('Topics Tree')))
        self.append_page(self.build_ix(), Gtk.Label(_('Index')))
        self.append_page(self.build_search_pane(), Gtk.Label(_('Search')))
        
    def build_ix(self):
        app,key=self.app,self.key
        s = Gtk.ListStore(str, str, str, bool, float) # label, normalized, url, is_page, scale
        self.ix = Gtk.TreeView()
        self.ix.set_model(s)
        col = Gtk.TreeViewColumn('Index', Gtk.CellRendererText(), markup = 0, scale = 4)
        col.mark_up = True
        col.set_sizing(Gtk.TreeViewColumnSizing.AUTOSIZE)
        col.set_resizable(True)
        col.set_expand(True)
        self.ix.insert_column(col, -1)
        self.ix.set_enable_search(True)
        self.ix.set_search_column(1)
        self.ix.set_headers_visible(False)
        self.ix.set_tooltip_column(0)
        p=[None]
        l=[]
        for e in self.app.get_ix(key):
            while(l and l[-1] >= e['level']): p.pop(); l.pop()
            it = s.append((
                    (" "*len(l))+e['name.utf8'],
                    normalize(e['name.utf8'].lower()),
                    e.get('local', ''),
                    e['is_page'],
                    max(0.5, 1.0-0.0625*len(l)), ))
            p.append(it)
            l.append(e['level'])
            self.ix_cont[e['local']] = [s.get_path(it), it]
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scroll.add(self.ix)
        self.ix.connect("cursor-changed", self._toc_cb)
        return scroll
    
    def build_toc_tree(self):
        app,key = self.app,self.key
        s = Gtk.TreeStore(str, str, str, bool) # label, normalized, url, is_page
        self.tree = Gtk.TreeView()
        self.tree.set_model(s)
        col = Gtk.TreeViewColumn('Topics', Gtk.CellRendererText(), markup = 0)
        col.mark_up = True
        col.set_sizing(Gtk.TreeViewColumnSizing.AUTOSIZE)
        col.set_resizable(True)
        col.set_expand(True)
        self.tree.insert_column(col, -1)
        self.tree.set_enable_search(True)
        self.tree.set_search_column(1)
        self.tree.set_headers_visible(False)
        self.tree.set_tooltip_column(0)
        p = [None]
        l = []
        for e in self.app.get_toc(key):
            while(l and l[-1] >= e['level']): p.pop(); l.pop()
            l.append(e['level'])
            it = s.append(p[-1],(e['name.utf8'], normalize(e['name.utf8'].lower()), e.get('local', ''), e['is_page']))
            p.append(it)
            if e.has_key('local'): self.tree_cont[e['local']] = [s.get_path(it), it]
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scroll.add(self.tree)
        self.tree.connect("cursor-changed", self._toc_cb)
        return scroll

    def _search_cb(self, e):
        m = self.results.get_model()
        m.clear()
        self.result_cont = {}
        e.modify_fg(Gtk.StateType.NORMAL, None)
        txt = e.get_text().strip()
        self.win.search_e.set_text(txt)
        enc = self.app.get_encoding(self.key)
        s,r = None,None
        try: s,r = self.app.get_chmf(self.key).Search(txt.encode(enc))
        except UnicodeDecodeError: pass
        if not s:
            print "no res", s, r
            e.modify_fg(Gtk.StateType.NORMAL, Gdk.color_parse("#FF0000"))
            return
        print len(r), "Found!"
        for k in r:
            k = _fix_entities(k)
            try: ku = k.decode('utf-8')
            except UnicodeDecodeError: ku = k.decode(enc)
            i = m.append(((ku, normalize(ku), r[k], True, 1.0, )))
            self.result_cont[r[k]] = [m.get_path(i),i]
            
    def build_search_pane(self):
        vb = Gtk.VBox()
        hb = Gtk.HBox(); vb.pack_start(hb, False, False, 2)
        self.search_e = e = Gtk.Entry()
        hb.pack_start(e, False, False, 2)
        s = Gtk.ListStore(str, str, str, bool, float) # label, normalized, url, is_page, scale
        self.results = Gtk.TreeView()
        self.results.set_model(s)
        col = Gtk.TreeViewColumn('Index', Gtk.CellRendererText(), markup = 0, scale = 4)
        col.mark_up = True
        col.set_sizing(Gtk.TreeViewColumnSizing.AUTOSIZE)
        col.set_resizable(True)
        col.set_expand(True)
        self.results.insert_column(col, -1)
        self.results.set_enable_search(True)
        self.results.set_search_column(1)
        self.results.set_headers_visible(False)
        self.results.set_tooltip_column(0)
        self.results.connect("cursor-changed", self._toc_cb)
        e.connect('activate', self._search_cb)

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scroll.add(self.results)
        vb.pack_start(scroll, True, True, 2)
        return vb

    def _toc_cb(self, tree, *a):
        if self.working: return
        try:
            s,i = tree.get_selection().get_selected()
        except AttributeError, e:
            print "Error:", e
            return
        is_page = self.win.gen_url(self.key, s.get_value(i, 3))
        if is_page:
            url = self.win.gen_url(self.key, s.get_value(i, 2))
            self.win._content.load(url)
        
class About(Gtk.AboutDialog):
    def __init__(self, parent):
        Gtk.AboutDialog.__init__(self, parent=parent)
        self.set_default_response(Gtk.ResponseType.CLOSE)
        self.connect('delete-event', lambda w, *a: w.hide() or True)
        self.connect('response', lambda w, *a: w.hide() or True)
        try: self.set_program_name("CHM View Kit")
        except AttributeError: pass
        self.set_logo_icon_name('chmviewkit')
        self.set_name("CHM View Kit")
        #self.set_version(version)
        self.set_copyright("Copyright © 2011, Ojuba Team <core@ojuba.org>")
        self.set_comments(_("CHM (Compiled HTML) Files Viewer"))
        self.set_license("""
            Released under terms of Waqf Public License.
            This program is free software; you can redistribute it and/or modify
            it under the terms of the latest version Waqf Public License as
            published by Ojuba.org.

            This program is distributed in the hope that it will be useful,
            but WITHOUT ANY WARRANTY; without even the implied warranty of
            MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.

            The Latest version of the license can be found on
            "http://waqf.ojuba.org/license"

""")
        self.set_website("http://git.ojuba.org/")
        self.set_website_label("http://git.ojuba.org")
        self.set_authors(["Muayyad Saleh Alsadi <alsadi@ojuba.org>", "Ehab El-Gedawy <ehabsas@gmail.com>"])
        self.run()
        self.destroy()
#    self.set_documenters(documenters)
#    self.set_artists(artists)
#    self.set_translator_credits(translator_credits)
#    self.set_logo(logo)



class MainWindow(Gtk.Window):
    def __init__(self, app, port, server):
        self.app = app
        self.port = port
        self.server = server # we need this to quit the server when closing main window
        self._open_dlg = None
        
        Gtk.Window.set_default_icon_name('chmviewkit')
        Gtk.Window.__init__(self)
        self.set_title(_('CHM View Kit'))
        self.set_default_size(600, 480)

        self.maximize()
        # add drag-data-recived action
        targets = Gtk.TargetList.new([])
        targets.add_uri_targets((1<<5)-1)
        self.drag_dest_set(Gtk.DestDefaults.ALL, [], Gdk.DragAction.COPY)
        self.drag_dest_set_target_list(targets)
        self.connect('drag-data-received', self.drop_data_cb)
        self.axl = Gtk.AccelGroup()
        self.add_accel_group(self.axl)
        
        vb = Gtk.VBox(); self.add(vb)

        tools = Gtk.Toolbar()
        vb.pack_start(tools, False, False, 2)
        
        self._content = ContentPane(self, None, _("CHM View Kit"))
        vb.pack_start(self._content,True, True, 2)
        
        ACCEL_CTRL_KEY, ACCEL_CTRL_MOD = Gtk.accelerator_parse("<Ctrl>")
        ACCEL_SHFT_KEY, ACCEL_SHFT_MOD = Gtk.accelerator_parse("<Shift>")
        b=Gtk.ToolButton.new_from_stock(Gtk.STOCK_OPEN)
        b.connect('clicked', self._open_cb)
        b.add_accelerator("clicked",self.axl,ord('o'), ACCEL_CTRL_MOD,Gtk.AccelFlags.VISIBLE)
        b.set_tooltip_text("%s\t‪%s‬" % (_("Open a CHM file"), "(Ctrl+O)" ))
        tools.insert(b, -1)

        b = Gtk.ToolButton.new_from_stock(Gtk.STOCK_PRINT)
        b.connect('clicked', lambda a: self._do_in_current_view("execute_script", 'window.print();'))
        b.add_accelerator("clicked",self.axl,ord('p'), ACCEL_CTRL_MOD,Gtk.AccelFlags.VISIBLE)
        b.set_tooltip_text("%s\t‪%s‬" % (_("Print current page"), "(Ctrl+P)" ))
        tools.insert(b, -1)

        tools.insert(Gtk.SeparatorToolItem(), -1)

        self.go_back_b = b = Gtk.ToolButton.new_from_stock(Gtk.STOCK_GO_BACK)
        b.set_sensitive(False)
        b.connect('clicked', lambda a: self._do_in_current_view("go_back"))
        b.add_accelerator("clicked",self.axl, Gdk.KEY_Left, ACCEL_CTRL_MOD, Gtk.AccelFlags.VISIBLE)
        b.set_tooltip_text("%s\t‪%s‬" % (_("Go Back"), "(Alt+Left)"))
        
        tools.insert(b, -1)

        self.go_forward_b = b = Gtk.ToolButton.new_from_stock(Gtk.STOCK_GO_FORWARD)
        b.set_sensitive(False)
        b.connect('clicked', lambda a: self._do_in_current_view("go_forward"))
        b.add_accelerator("clicked",self.axl, Gdk.KEY_Right, ACCEL_CTRL_MOD, Gtk.AccelFlags.VISIBLE)
        b.set_tooltip_text("%s\t‪%s‬" % (_("Go Forward"), "(Alt+Right)"))
        tools.insert(b, -1)

        tools.insert(Gtk.SeparatorToolItem(), -1)

        #tools.insert(Gtk.SeparatorToolItem(), -1)

        img = Gtk.Image()
        img.set_from_stock(Gtk.STOCK_ZOOM_IN, Gtk.IconSize.BUTTON)
        b = Gtk.ToolButton(icon_widget=img, label=_("Zoom in"))
        b.set_is_important(True)
        b.add_accelerator("clicked",self.axl,Gdk.KEY_equal, ACCEL_CTRL_MOD, Gtk.AccelFlags.VISIBLE)
        b.add_accelerator("clicked",self.axl,Gdk.KEY_plus, ACCEL_CTRL_MOD, Gtk.AccelFlags.VISIBLE)
        b.add_accelerator("clicked",self.axl,Gdk.KEY_KP_Add, ACCEL_CTRL_MOD, Gtk.AccelFlags.VISIBLE)
        b.set_tooltip_text("%s\t‪%s‬" % (_("Makes things appear bigger"), "(Ctrl++)"))
        b.connect('clicked', lambda a: self._do_in_current_view("zoom_in"))
        tools.insert(b, -1)

        img = Gtk.Image()
        img.set_from_stock(Gtk.STOCK_ZOOM_OUT, Gtk.IconSize.BUTTON)
        b = Gtk.ToolButton(icon_widget=img, label=_("Zoom out"))
        b.add_accelerator("clicked",self.axl,Gdk.KEY_minus, ACCEL_CTRL_MOD, Gtk.AccelFlags.VISIBLE)
        b.add_accelerator("clicked",self.axl,Gdk.KEY_KP_Subtract, ACCEL_CTRL_MOD, Gtk.AccelFlags.VISIBLE)
        b.set_tooltip_text("%s\t‪%s‬" % (_("Makes things appear smaller"), "(Ctrl+-)"))
        b.connect('clicked', lambda a: self._do_in_current_view("zoom_out"))
        tools.insert(b, -1)

        img = Gtk.Image()
        img.set_from_stock(Gtk.STOCK_ZOOM_100, Gtk.IconSize.BUTTON)
        b = Gtk.ToolButton(icon_widget = img, label = _("1:1 Zoom"))
        b.add_accelerator("clicked",self.axl,ord('0'), ACCEL_CTRL_MOD, Gtk.AccelFlags.VISIBLE)
        b.add_accelerator("clicked",self.axl,Gdk.KEY_KP_0, ACCEL_CTRL_MOD, Gtk.AccelFlags.VISIBLE)
        b.set_tooltip_text("%s\t‪%s‬" % (_("Restore original zoom factor"), "(Ctrl+0)"))
        b.connect('clicked', lambda a: self._do_in_current_view("set_zoom_level",1.0))
        tools.insert(b, -1)

        tools.insert(Gtk.SeparatorToolItem(), -1)

        self.search_e = e = Gtk.Entry()
        e.connect('activate', self.search_cb)
        e.add_accelerator("activate",self.axl,Gdk.KEY_g, ACCEL_CTRL_MOD, Gtk.AccelFlags.VISIBLE)
        b = Gtk.ToolItem()
        b.add(e)
        tools.insert(b, -1)

        # Add CTRL+F accelerator for focusing search entry
        self.axl.connect(Gdk.KEY_F, ACCEL_CTRL_MOD, Gtk.AccelFlags.VISIBLE, self.find_cb)
        # Add CTRL+SHIFT+G accelerator for backward search
        self.axl.connect(Gdk.KEY_g, ACCEL_CTRL_MOD|ACCEL_SHFT_MOD, \
                                                     Gtk.AccelFlags.VISIBLE, lambda *a: self.search_cb(None, False))

        tools.insert(Gtk.SeparatorToolItem(), -1)
        b = Gtk.ToolButton.new_from_stock(Gtk.STOCK_ABOUT)
        b.connect('clicked', self._show_about_dlg)
        b.set_tooltip_text(_("About CHM View Kit"))
        tools.insert(b, -1)

        self.connect("delete_event", self.quit)
        self.connect("destroy", self.quit)
        self.show_all()

    def find_cb(self, *a):
        if not self.search_e.is_focus():
            self.search_e.set_text(self._do_in_current_view('eval_js', 'document.getSelection().toString()'))
        self.search_e.grab_focus()
        self.search_e.select_region(0, len(self.search_e.get_text()))
        self.search_cb(self.search_e)

    def _do_highlight(self, txt):
        view = self._get_current_view()
        view.set_highlight_text_matches(False)
        view.unmark_text_matches()
        view.mark_text_matches(txt, False, False)
        view.set_highlight_text_matches(True)
        
    def search_cb(self, e, forward = True):
        txt = self.search_e.get_text()
        view = self._get_current_view()
        self.search_e.modify_fg(Gtk.StateType.NORMAL, None)
        if not view or not txt: return None
        # returns False if not found
        s = view.search_text(txt, False, forward, True) # txt, case, forward, wrap
        self._do_highlight(txt)
        if not s: 
            self.search_e.modify_fg(Gtk.StateType.NORMAL, Gdk.color_parse("#FF0000"))

    def _show_about_dlg(self, *a):
        return About(self)

    def _show_open_dlg(self, *a):
        if self._open_dlg:
            return self._open_dlg.run()
        self._open_dlg = Gtk.FileChooserDialog("Select files to import",
                                               parent = self,
                                               buttons = (Gtk.STOCK_CANCEL,
                                               Gtk.ResponseType.REJECT,
                                               Gtk.STOCK_OK,
                                               Gtk.ResponseType.ACCEPT))
        ff = Gtk.FileFilter()
        ff.set_name(_('CHM Files'))
        ff.add_mime_type('application/x-chm')
        ff.add_mime_type('application/chm')
        self._open_dlg.add_filter(ff)
        ff = Gtk.FileFilter()
        ff.set_name(_('All files'))
        ff.add_pattern('*')
        self._open_dlg.add_filter(ff)
        self._open_dlg.set_select_multiple(False)
        self._open_dlg.connect('delete-event', lambda w,*a: w.hide() or True)
        self._open_dlg.connect('response', lambda w,*a: w.hide() or True)
        return self._open_dlg.run()

    def gen_url(self, key, fn):
        return "http://127.0.0.1:%d/%s$/%s" % (self.port, key, fn)

    def _open_cb(self, *a):
        if self._show_open_dlg() != Gtk.ResponseType.ACCEPT: return
        chmfn = self._open_dlg.get_filename()
        if os.path.exists(chmfn):
            manager = Gtk.RecentManager.get_default()
            manager.add_item(chmfn)
        self._do_open(chmfn)
        
    def _do_open(self, chmfn):
        fn = ""
        try:
            # FIXME: have a single method for this
            key = self.app.load_chm(chmfn)
            fn = self.app.get_toc(key)[0]['local']    # FIXME: just put cursor to first is_page
        except IOError: error(_("unable to open file [%s]!") % chmfn,None); return
        except KeyError: pass
        except IndexError: pass
        self._content.new_tab(self.gen_url(key, fn), key)
        pane = BookSidePane(self, self.app, key)
        self.app.chm[key]["pane"] = pane
        l = Gtk.Label('sss')
        n = self._content.sidepane.append_page(pane, l)
        self._content.sidepane.get_nth_page(n).show_all()
        self._content.sidepane.set_current_page(n)
    
    def _get_current_view(self):
        n = self._content.tabs.get_current_page()
        if n < 0:
            return None
        return self._content.tabs.get_nth_page(n).get_child()
        
    
    def _do_in_current_view (self, action, *a, **kw):
         view = self._get_current_view()
         if not view: return None
         return getattr(view, action)(*a,**kw)

    def _do_in_all_views (self, action, *a, **kw):
         for n in range(self._content.tabs.get_n_pages()):
             view = self._content.tabs.get_nth_page(n).get_child()
             getattr(view, action)(*a,**kw)

    def drop_data_cb(self, widget, dc, x, y, selection_data, info, t):
        for chmfn in selection_data.get_uris():
            if chmfn.startswith('file://'):
                f = unquote(chmfn[7:])
                self._do_open(f)
            else:
                print "Protocol not supported in [%s]" % chmfn
        #dc.drop_finish (True, t);

    def quit(self,*args):
        self.server.running = False
        Gtk.main_quit()
        return False

CHM_HIGH_PORT = 18080

def launchServer(app):
    launched = False
    port = CHM_HIGH_PORT
    while(not launched):
        try:
            server = httpserver.serve(app,
                                      host = '127.0.0.1',
                                      port = port,
                                      start_loop = False)
        except socket.error:
            port+=1
        else:
            launched = True
    return port, server

class ChmWebApp:
    _mimeByExtension = {
        'html': 'text/html', 'htm': 'text/html', 'txt': 'text/plain',
        'css': 'text/css', 'js':'application/javascript',
        'ico': 'image/x-icon', 'png': 'image/png', 'gif': 'image/gif',
        'jpg': 'image/jpeg', 'jpeg': 'image/jpeg'
    }
    _li_re = re.compile(r'''(</?(?:ul|li)[^>]*>)''', re.I | re.S | re.M)
    _p_re = re.compile(r'''<param([^<>]+)>''', re.I | re.S | re.M)
    _kv_re = re.compile(r'''(\S+)\s*=\s*("([^"]*)"|'([^']*)')''', re.I | re.S | re.M)
    _href_re = re.compile(r'''(<[^<>]+(?:href|src)=(["'])/)''', re.I | re.S | re.M)
    _chr_re = re.compile(r'''<meta[^>]*content\s*=\s*['"]?text/html;\s*charset\s*=\s*([^ '">]+)\s*['"]?[^>]*>''', re.I | re.S | re.M)
    
    def __init__(self):
        self.key2file = {}
        self.chm = {}
        #self.chmf.LoadCHM('sayed-elkhater.chm')
        

    def __call__(self, environ, start_response):
        uri = environ['PATH_INFO']
        l = uri[1:].split('$/', 1) # we have the a key followed by $/ then the rest of the uri
        if len(l) == 2:
            key,fn = l
            fn = '/'+fn
        else:
            # in case of no key guess it from referrer
            ref = environ.get('HTTP_REFERER','')
            (scheme, netloc, path, query, fragment) = urlsplit(ref)
            if ref and '$' in path:
                l = path[1:].split('$', 1)
                key = l[0]
                fn = uri
                # we can continue without redirect,
                # but it's better to redirect so that we always have a valid referrer
                start_response("302 moved", [('content-type', 'text/plain'),
                                             ('Location', "/"+key+"$"+fn)])
                return ("moved",)
            else:
                # in case of no key and no valid referrer give 404
                start_response("404 Not found", [('content-type', 'text/plain')])
                return ('not found',)

        ext = fn[fn.rfind('.'):][1:].lower()
        mime = self._mimeByExtension.get(ext,"application/octet-stream")
        chmf = self.get_chmf(key)
        s,u = chmf.ResolveObject(fn)
        if s != 0:
            start_response("404 Not found", [('content-type', 'text/plain')])
            return ('not found',)
        l,data = chmf.RetrieveObject(u)
        start_response("200 OK", [('content-type', mime)])
        # to test referrer fix comment out next line
        if ext == 'htm':
            data = self._href_re.sub(r'\1'+key+'$/',data)
            self.get_encoding(key, data)
        return (data,)

    def load_chm(self, fn):
        key = hashlib.md5(fn).digest().encode('base64')[:-3].replace('/', '_').replace('+', '-')
        if self.key2file.has_key(key):
            return key
        self.key2file[key] = fn
        return key

    def get_chmf(self, key):
        if not self.chm.has_key(key):
            self.chm[key] = {}
        if not self.chm[key].has_key('chmf'):
            fn = self.key2file[key]
            chmf = chm.CHMFile()
            s = chmf.LoadCHM(fn)
            if s != 1:
                raise IOError
            self.chm[key]['chmf'] = chmf
        return self.chm[key]['chmf']

    def get_encoding(self, key, html=''):
        if self.chm[key].has_key('encoding'):
            return self.chm[key]['encoding']
        f, e = self.guess_encoding(html)
        if f and e:
            self.chm[key]['encoding'] = e
        else:
            e = 'windows-1256'
        return e

    def guess_encoding(self, html = ''):
        m = self._chr_re.search(html)
        if m:
            return True, m.group(1).strip()
        e = 'UTF-8'
        try:
            t = html.decode(e)
        except UnicodeDecodeError:
            return False, e
        return False, None
    
    def _parse_toc_html(self, html, home = None, title = None):
        html = _fix_entities(html)
        li = self._li_re
        p = self._p_re
        level = 0
        toc = []
        home = home.lstrip('/')
        home_found = False
        for i in li.split(html or ""):
            e = {}
            ul = i.lower()
            if ul.startswith('<ul'):
                level += 1
            elif ul.startswith('</ul'):
                level -= 1
            for m in p.findall(i):
                param = {}
                for kvm in self._kv_re.findall(m):
                    k, v = kvm[0], kvm[1]
                    param[k.lower().strip(" \t\n\r\"'")] = v.strip(" \t\n\r\"'")
                if param.has_key('name') and param.has_key('value'):
                    e[param['name'].lower()] = param['value']
                    try:
                        u = param['value'].decode('utf-8')
                    except UnicodeDecodeError:
                        u = param['value'].decode('windows-1256')
                    e[param['name'].lower()+'.utf8'] = u
            e['level'] = level
            e['is_page'] = e.has_key('local')
            if not home_found and e.has_key('local') and home and e["local"] == home:
                home_found = True
            if e.has_key('name'):
                toc.append(e)
        if home and not home_found:
            i = home
            t = title or home
            try:
                u = t.decode('utf-8')
            except UnicodeDecodeError:
                u = t.decode('windows-1256')
            e = {'is_page': True, 'level': 1, 'name.utf8': u, 'local': i, 'name': t}
            toc.insert(0, e)
        return toc

    def _enum_cb(self, f, u, d):
        fn = u.path
        if fn.startswith('/'):
            fn = fn[1:]
        ext = (fn[fn.rfind('.'):][1:].lower())[:3]
        if ext == 'htm':
            d.append(fn)

    def get_toc(self, key):
        chmf = self.get_chmf(key)
        if self.chm[key].has_key('toc'):
            return self.chm[key]['toc']
        #d=[]
        #chmlib.chm_enumerate_dir(chmf.file, '/', chmlib.CHM_ENUMERATE_NORMAL , self._enum_cb, d)
        html = chmf.GetTopicsTree() or ''
        self.get_encoding(key, html)
        toc = self._parse_toc_html(html, chmf.home, chmf.title)
        self.chm[key]['toc'] = toc
        return toc

    def get_ix(self, key):
        chmf = self.get_chmf(key)
        if self.chm[key].has_key('ix'):
            return self.chm[key]['ix']
        html = chmf.GetIndex() or ''
        self.get_encoding(key, html)
        ix = self._parse_toc_html(html, chmf.home, chmf.title)
        self.chm[key]['ix'] = ix
        return ix


def main():
    exedir = os.path.dirname(sys.argv[0])
    ld = os.path.join(exedir,'..','share','locale')
    if not os.path.isdir(ld):
        ld = os.path.join(exedir, 'locale')
    gettext.install('chmviewkit', ld, unicode=0)

    app = ChmWebApp()
    port, server = launchServer(app)
    GObject.threads_init()
    threading.Thread(target = server.serve_forever, args = ()).start()
    while(not server.running):
        time.sleep(0.25)
    Gdk.threads_enter()
    w = MainWindow(app, port, server)
    for fn in sys.argv[1:]:
        if not os.path.exists(fn):
            continue
        w._do_open(fn)
    try: 
        Gtk.main()
    except KeyboardInterrupt: 
        server.running=False
    Gdk.threads_leave()

if __name__ == "__main__":
    main()
