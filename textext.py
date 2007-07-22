#!/usr/bin/env python
"""
=======
textext
=======

:Author: Pauli Virtanen <pav@iki.fi>
:Author: Robert Szalai <szalai@mm.bme.hu>
:Date: 2007-07-19
:License: BSD

Textext is an extension for Inkscape_ that allows adding
LaTeX-generated text objects to your SVG drawing. What's more, you can
also *edit* these text objects after creating them.

This brings some of the power of TeX typesetting to Inkscape.

Textext was initially based on InkLaTeX_ written by Toru Araki,
but is now rewritten.

.. note::
   Unfortunately, the TeX input dialog is modal. That is, you cannot
   do anything else with Inkscape while you are composing the LaTeX
   text snippet.

   This is because I have not yet worked out whether it is possible to
   write asynchronous extensions for Inkscape.

.. note::
   Textext requires Pdflatex and one of the following
     - Pdf2svg_
     - Pstoedit_ compiled with the ``plot-svg`` back-end
     - Pstoedit_ and Skconvert_

.. _Pstoedit: http://www.pstoedit.net/pstoedit
.. _Skconvert: http://www.skencil.org/
.. _Pdf2svg: http://www.cityinthesky.co.uk/pdf2svg.html
.. _Inkscape: http://www.inkscape.org/
.. _InkLaTeX: http://www.kono.cis.iwate-u.ac.jp/~arakit/inkscape/inklatex.html
"""

#------------------------------------------------------------------------------

__version__ = "0.3"
__author__ = "Pauli Virtanen <pav@iki.fi>, Robert Szalai <szalai@mm.bme.hu>"
__docformat__ = "restructuredtext en"

import sys
sys.path.append('/usr/share/inkscape/extensions')

import inkex
import os, sys, tempfile, traceback, glob, re
import xml.dom.ext.reader.Sax2
from xml.dom.NodeFilter import NodeFilter

import pygtk
pygtk.require('2.0')
import gtk

TEXTEXT_NS = "http://www.iki.fi/pav/software/textext/"
SVG_NS = "http://www.w3.org/2000/svg"
XLINK_NS = "http://www.w3.org/1999/xlink"

ID_PREFIX = "textext-obj-"

#------------------------------------------------------------------------------
# Inkscape plugin functionality & GUI
#------------------------------------------------------------------------------

class AskText(object):
    """GUI for editing TexText objects"""
    def __init__(self, text, preamble_file, scale_factor):
        self.text = text
        self.preamble_file = preamble_file
        self.scale_factor = scale_factor

    def ask(self):
        window = gtk.Window(gtk.WINDOW_TOPLEVEL)
        window.set_title("TeX Text")
        window.set_default_size(400, 200)

        label1 = gtk.Label(u"Preamble file:")
        label2 = gtk.Label(u"Scale factor:")
        label3 = gtk.Label(u"Text:")

        self._preamble = gtk.Entry()
        self._preamble.set_text(self.preamble_file)

        self._scale_adj = gtk.Adjustment(value=self.scale_factor,
                                         lower=0.01, upper=100,
                                         step_incr=0.1, page_incr=1)
        self._scale = gtk.SpinButton(self._scale_adj, digits=2)

        self._text = gtk.TextView()
        self._text.get_buffer().set_text(self.text)

        ok = gtk.Button(stock=gtk.STOCK_OK)

        # layout
        table = gtk.Table(3, 2, False)
        table.attach(label1,         0,1,0,1,xoptions=0,yoptions=gtk.FILL)
        table.attach(self._preamble, 1,2,0,1,yoptions=gtk.FILL)
        table.attach(label2,         0,1,1,2,xoptions=0,yoptions=gtk.FILL)
        table.attach(self._scale,    1,2,1,2,yoptions=gtk.FILL)
        table.attach(label3,         0,1,2,3,xoptions=0,yoptions=gtk.FILL)
        table.attach(self._text,     1,2,2,3)

        vbox = gtk.VBox(False, 5)
        vbox.pack_start(table)
        vbox.pack_end(ok, expand=False)

        window.add(vbox)

        # signals
        window.connect("delete-event", self.cb_delete_event)
        ok.connect("clicked", self.cb_ok)

        # run
        window.show_all()
        gtk.main()

        return self.text, self.preamble_file, self.scale_factor

    def cb_delete_event(self, widget, event, data=None):
        gtk.main_quit()
        return False
    
    def cb_ok(self, widget, data=None):
        buf = self._text.get_buffer()
        self.text = buf.get_text(buf.get_start_iter(),
                                 buf.get_end_iter())
        self.preamble_file = self._preamble.get_text()
        self.scale_factor = self._scale_adj.get_value()
        gtk.main_quit()
        return False

class TexText(inkex.Effect):
    def __init__(self):
        inkex.Effect.__init__(self)
        self.OptionParser.add_option(
            "-t", "--text", action="store", type="str",
            dest="text", default=None)
        self.OptionParser.add_option(
            "-p", "--preamble-file", action="store", type="str",
            dest="preamble_file", default="header.inc")
        self.OptionParser.add_option(
            "-s", "--scale-factor", action="store", type="float",
            dest="scale_factor", default=1.0)

    def effect(self):
        """Perform the effect: create/modify TexText objects"""
        global CONVERTERS

        # Pick a converter
        converter_cls = None
        for conv_cls in CONVERTERS:
            if conv_cls.available():
                converter_cls = conv_cls
                break

        if not converter_cls:
            raise RuntimeError("No Latex -> SVG converter available")
        
        # Find root element
        old_node, text, preamble_file = self.get_old()
        
        # Ask for TeX code
        if self.options.text is None:
            asker = AskText(text, preamble_file, 1.0)
            text, preamble_file, scale_factor = asker.ask()
        else:
            text = self.options.text
            preamble_file = self.options.preamble_file
            scale_factor = self.options.scale_factor

        if not text:
            return

        # Convert
        converter = converter_cls(self.document)
        try:
            new_node = converter.convert(text, preamble_file, scale_factor)
        finally:
            converter.finish()
        
        if new_node is None:
            return # noop

        # Insert into document

        new_node.setAttributeNS(TEXTEXT_NS,
                                'textext:text',
                                text.encode('string-escape'))
        
        new_node.setAttributeNS(TEXTEXT_NS, 'textext:preamble',
                                preamble_file.encode('string-escape'))

        if old_node and old_node.hasAttribute('transform'):
            new_node.setAttribute('transform',
                                  old_node.getAttribute('transform'))
        
        self.replace_node(old_node, new_node)

    def get_old(self):
        """
        Dig out LaTeX code and name of preamble file from old
        TexText-generated objects.

        :Returns: (old_node, latex_text, preamble_file_name)
        """

        for i in self.options.ids:
            node = self.selected[i]
            if node.tagName != 'g': continue
            
            if node.hasAttributeNS(TEXTEXT_NS, 'text'):
                # starting from 0.2, use namespaces
                return (node,
                        node.getAttributeNS(TEXTEXT_NS, 'text').decode('string-escape'),
                        node.getAttributeNS(TEXTEXT_NS, 'preamble').decode('string-escape'))
            elif node.hasAttribute('textext'):
                # < 0.2 backward compatibility
                return (node,
                        node.getAttribute('textext').decode('string-escape'),
                        node.getAttribute('texpreamble').decode('string-escape'))
        return None, "", "header.inc"

    def fix_xml_namespace(self, node):
        """
        Set the default XML namespace to http://www.w3.org/2000/svg
        for the given node and all its children.

        This is needed since pstoedit plot-svg generates namespaceless
        SVG files.
        """
        node.setAttributeNS('http://www.w3.org/2000/xmlns/', 'xmlns', SVG_NS)
        for c in node.childNodes:
            if c.nodeType == c.ELEMENT_NODE:
                self.fix_xml_namespace(c)

    def replace_node(self, old_node, new_node):
        """
        Replace an XML node old_node with new_node
        in self.document.
        """
        new_node = self.document.importNode(new_node, True)
        self.fix_xml_namespace(new_node)
        if old_node is None:
            self.document.documentElement.appendChild(new_node)
        else:
            parent = old_node.parentNode
            parent.removeChild(old_node)
            parent.appendChild(new_node)
        

#------------------------------------------------------------------------------
# LaTeX converters
#------------------------------------------------------------------------------

try:
    import subprocess

    def exec_command(cmd, ok_return_value=0, combine_error=False):
        """
        Run given command, check return value, and return
        concatenated stdout and stderr.
        """
        try:
            p = subprocess.Popen(cmd,
                                 stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE,
                                 stdin=subprocess.PIPE)
            out, err = p.communicate()
        except OSError, e:
            raise RuntimeError("Command %s failed: %s" % (' '.join(cmd), e))
        
        if ok_return_value is not None and p.returncode != ok_return_value:
            raise RuntimeError("Command %s failed (code %d): %s"
                               % (' '.join(cmd), p.returncode, out + err))
        return out + err
  
except ImportError:

    # Python < 2.4 ...
    import popen2
    
    def exec_command(cmd, ok_return_value=0, combine_error=False):
        """
        Run given command, check return value, and return
        concatenated stdout and stderr.
        """
        
        # XXX: unix-only!

        try:
            p = popen2.Popen4(cmd, True)
            p.tochild.close()
            returncode = p.wait() >> 8
            out = p.fromchild.read()
        except OSError, e:
            raise RuntimeError("Command %s failed: %s" % (' '.join(cmd), e))
        
        if ok_return_value is not None and returncode != ok_return_value:
            raise RuntimeError("Command %s failed (code %d): %s"
                               % (' '.join(cmd), returncode, out))
        return out


class LatexConverterBase(object):
    """
    Base class for Latex -> SVG converters
    """

    # --- Public api
    
    def __init__(self, document):
        """
        Initialize Latex -> SVG converter.

        :Parameters:
          - `document`: Document where the result is to be embedded (read-only)
        """
        self.tmp_path = tempfile.mkdtemp()
        self.tmp_base = 'tmp'

    def convert(self, latex_text, preamble_file, scale_factor):
        """
        Return an XML node containing latex text

        :Parameters:
          - `latex_text`: Latex code to use
          - `preamble_file`: Name of a preamble file to include
          - `scale_factor`: Scale factor to use if object doesn't have
                            a ``transform`` attribute.

        :Returns: XML DOM node
        """
        raise NotImplementedError

    def available(cls):
        """
        :Returns: Whether this converter is available
        """
        return False
    available = classmethod(available)

    def finish(self):
        """
        Clean up any temporary files
        """
        self.remove_temp_files()

    # --- Internal

    def tmp(self, suffix):
        """
        Return a file name corresponding to given file suffix,
        and residing in the temporary directory.
        """
        return os.path.join(self.tmp_path,
                            self.tmp_base + '.' + suffix)

    def tex_to_pdf(self, latex_text, preamble_file):
        """
        Create a PDF file from latex text
        """
        
        # Read preamble
        preamble = ""
        if os.path.exists(preamble_file):
            f = open(preamble_file, 'r')
            preamble += f.read()
            f.close()
        
        # Options pass to LaTeX-related commands
        latexOpts = ['-interaction=nonstopmode',
                     '-halt-on-error']
        
        texwrapper = r"""
        \documentclass[landscape,a0]{article}
        %s
        \pagestyle{empty}
        \begin{document}
        \noindent
        %s
        \end{document}
        """ % (preamble, latex_text)
        
        cwd = os.getcwd()
        os.chdir(self.tmp_path)
        
        # Convert TeX to PDF
        try:
            # Write tex
            f_tex = open(self.tmp('tex'), 'w')
            try:
                f_tex.write(texwrapper)
            finally:
                f_tex.close()
            
            # Exec pdflatex: tex -> pdf
            exec_command(['pdflatex', self.tmp('tex')] + latexOpts)
            if not os.path.exists(self.tmp('pdf')):
                raise RuntimeError("pdflatex didn't produce output")
        finally:
            os.chdir(cwd)

    def remove_temp_files(self):
        """Remove temporary files"""
        base = os.path.join(self.tmp_path, self.tmp_base)
        for filename in glob.glob(base + '*'):
            self.try_remove(filename)
        self.try_remove(self.tmp_path)

    def try_remove(self, filename):
        """Try to remove given file, skipping if not exists."""
        if os.path.isfile(filename):
            os.remove(filename)
        elif os.path.isdir(filename):
            os.rmdir(filename)

class PdfConverterBase(LatexConverterBase):
    def convert(self, latex_text, preamble_file, scale_factor):
        self.tex_to_pdf(latex_text, preamble_file)
        self.pdf_to_svg()
        
        new_node = self.svg_to_group()
        if not new_node:
            return None
        
        new_node.setAttribute('transform', self.get_transform(scale_factor))
        return new_node

    def pdf_to_svg(self):
        """Convert the PDF file to a SVG file"""
        raise NotImplementedError

    def get_transform(self, scale_factor):
        """Get a suitable default value for the transform attribute"""
        raise NotImplementedError

    def svg_to_group(self):
        """
        Convert the SVG file to an SVG group node.

        :Returns: <svg:g> node
        """

        # create xml.dom representation of the TeX file
        svg_stream = open(self.tmp('svg'), 'r')
        try:
            reader_tex = xml.dom.ext.reader.Sax2.Reader()
            doc_tex = reader_tex.fromStream(svg_stream)
        finally:
            svg_stream.close()

        docel = doc_tex.documentElement
        
        # get latex paths from svg_out
        try:
            return docel.getElementsByTagName('g')[0]
        except IndexError:
            return None

class SkConvert(PdfConverterBase):
    """
    Convert PDF -> SK -> SVG using pstoedit and skconvert
    """
    def get_transform(self, scale_factor):
        return 'scale(%f,%f)' % (scale_factor, scale_factor)

    def pdf_to_svg(self):
        # Options for pstoedit command
        pstoeditOpts = '-dt -ssp -psarg "-r9600x9600"'.split()

        # Exec pstoedit: pdf -> sk
        exec_command(['pstoedit', '-f', 'sk',
                      self.tmp('pdf'), self.tmp('sk')]
                     + pstoeditOpts)
        if not os.path.exists(self.tmp('sk')):
            raise RuntimeError("pstoedit didn't produce output")

        # Exec skconvert: sk -> svg
        os.environ['LC_ALL'] = 'C'
        exec_command(['skconvert', self.tmp('sk'), self.tmp('svg')])
        if not os.path.exists(self.tmp('svg')):
            raise RuntimeError("skconvert didn't produce output")

    def available(cls):
        """Check whether skconvert and pstoedit are available"""
        try:
            exec_command(['pstoedit'], ok_return_value=1)
            exec_command(['skconvert'], ok_return_value=1)
            return True
        except RuntimeError:
            return False
    available = classmethod(available)

class PstoeditPlotSvg(PdfConverterBase):
    """
    Convert PDF -> SVG using pstoedit's plot-svg backend
    """
    def get_transform(self, scale_factor):
        return 'matrix(%f,0,0,%f,%f,%f)' % (
            scale_factor, -scale_factor,
            -200*scale_factor, 750*scale_factor)
    
    def pdf_to_svg(self):
        # Options for pstoedit command
        pstoeditOpts = '-dt -ssp -psarg "-r9600x9600"'.split()

        # Exec pstoedit: pdf -> svg
        exec_command(['pstoedit', '-f', 'plot-svg',
                      self.tmp('pdf'), self.tmp('svg')]
                     + pstoeditOpts)
        if not os.path.exists(self.tmp('svg')):
            raise RuntimeError("pstoedit didn't produce output")

    def available(cls):
        """Check whether pstoedit has plot-svg available"""
        try:
            out = exec_command(['pstoedit', '-help'], ok_return_value=1)
            return 'plot-svg' in out
        except RuntimeError:
            return False
    available = classmethod(available)

class Pdf2Svg(PdfConverterBase):
    """
    Convert PDF -> SVG using pdf2svg
    """
    def __init__(self, document):
        PdfConverterBase.__init__(self, document)
        self.id_start = self.find_glyph_id_limits(document)

    def find_glyph_id_limits(self, document):
        """
        Find the first free id in the document
        """
        walker = document.createTreeWalker(document.documentElement,
                                           NodeFilter.SHOW_ELEMENT, None, 0)
        startid = 0

        while True:
            if walker.currentNode.hasAttribute('id'):
                curid = walker.currentNode.getAttribute('id')
                if curid.startswith(ID_PREFIX):
                    try:
                        startid = max(startid, int(curid[len(ID_PREFIX):]))
                    except ValueError:
                        pass # not a glyph of ours, skip it

            if not walker.nextNode():
                break

        return startid

    def pdf_to_svg(self):
        exec_command(['pdf2svg', self.tmp('pdf'), self.tmp('svg'), '1'])

    def get_transform(self, scale_factor):
        return 'scale(%f,%f)' % (scale_factor, scale_factor)

    def svg_to_group(self):
        # create xml.dom representation of the TeX file
        svg_stream = open(self.tmp('svg'), 'r')
        try:
            reader_tex = xml.dom.ext.reader.Sax2.Reader()
            doc_tex = reader_tex.fromStream(svg_stream)
        finally:
            svg_stream.close()

        href_map = {}

        docel = doc_tex.documentElement

        # Map items to new ids
        walker = doc_tex.createTreeWalker(docel, NodeFilter.SHOW_ELEMENT, None, 0)
        while True:
            if walker.currentNode.hasAttribute('id'):
                curid = walker.currentNode.getAttribute('id')

                self.id_start += 1
                new_id = "%s%d" % (ID_PREFIX, self.id_start)
                
                href_map['#' + curid] = '#' + new_id
                walker.currentNode.setAttribute('id', new_id)

            if not walker.nextNode():
                break

        # Replace hrefs
        url_re = re.compile('^url\((.*)\)$')
        
        walker = doc_tex.createTreeWalker(docel, NodeFilter.SHOW_ELEMENT, None, 0)
        while True:
            if walker.currentNode.hasAttributeNS(XLINK_NS, 'href'):
                curid = walker.currentNode.getAttributeNS(XLINK_NS, 'href')
                walker.currentNode.setAttributeNS(XLINK_NS, 'href',
                                                  href_map.get(curid, curid))

            if walker.currentNode.hasAttribute('clip-path'):
                value = walker.currentNode.getAttribute('clip-path')
                m = url_re.match(value)
                if m:
                    walker.currentNode.setAttribute(
                        'clip-path',
                        'url(%s)' % href_map.get(m.group(1), m.group(1)))

            if not walker.nextNode():
                break
        
        # Bundle everything in a single group
        master_group = doc_tex.createElementNS(SVG_NS, 'g')
        for c in list(doc_tex.documentElement.childNodes):
            master_group.appendChild(c)
        return master_group

    def available(cls):
        """Check whether pdf2svg is available"""
        try:
            exec_command(['pdf2svg'], ok_return_value=254)
            return True
        except RuntimeError:
            return False
    available = classmethod(available)

CONVERTERS = [Pdf2Svg, PstoeditPlotSvg, SkConvert]

#------------------------------------------------------------------------------
# Entry point
#------------------------------------------------------------------------------

if __name__ == "__main__":
    e = TexText()
    e.affect()
