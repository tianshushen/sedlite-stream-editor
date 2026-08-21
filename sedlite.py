#!/usr/bin/env python3
#
# Author: Shen, Tianshu
#
# SedLite - a subset of the sed stream editor.
#
# The script is parsed once into a list of Command objects, which are then
# applied to each input line as it is read.  The input is never stored: only
# one line of look-ahead is kept, which is what makes the $ address possible.

import sys
import re
import os
import tempfile

COMMANDS='qpdsaic:bt'  # every command letter SedLite understands
PROGRAM='sedlite'  # the name used in messages; the spec allows hard-coding it
failed=False  # set when a file could not be opened, so we exit 1 at the end

class Command:
    def __init__(self,ctype:str,atype:str,address:"int|str",patype:str=None,padress:"int|str"=None,additional:"str|None"=None):
        self.ctype=ctype
        self.atype=atype
        self.address=address
        self.patype=patype  # type of the second address of a range
        self.padress=padress  # value of the second address of a range
        self.additional=additional  # s parts, a/i/c text, or a b/t/: label
        self.inrange=False  # currently inside this command's range?

class Parser:  # scans a script one character at a time
    def __init__(self,text:str,source:str=None):
        self.text=text
        self.pointer=0
        self.source=source  # script file name, or None for the command line

    def invalid(self):
        """Report a script that can not be parsed and exit."""
        if self.source is None:
            terminate('command line: invalid command')
        linenum=self.text.count('\n',0,self.pointer)+1
        terminate(f'file {self.source} line {linenum}: invalid command')

    def clean(self):  # skip separators and comments between commands
        while self.pointer<len(self.text):
            char=self.text[self.pointer]
            if char in (' ','\t','\n',';'):
                self.pointer+=1
            elif char=='#':
                while self.pointer<len(self.text) and self.text[self.pointer]!='\n':
                    self.pointer+=1
            else:
                break

    def delspace(self):  # skip spaces and tabs inside a command
        while self.pointer<len(self.text) and self.text[self.pointer] in (' ','\t'):
            self.pointer+=1

    def multiparse(self):
        commands=[]
        while True:
            self.clean()
            if self.pointer>=len(self.text):
                return commands
            commands.append(self.parse())

    def parse_address(self)->tuple:
        """Parse one address, or return (None,None) if there is none here."""
        if self.pointer>=len(self.text):
            return (None,None)
        char=self.text[self.pointer]
        atype,address=None,None
        if char=='$':
            self.pointer+=1
            atype='dollar'
            address=None
            return (atype,address)
        elif char.isdigit():
            atype='digit'
            start=self.pointer
            while self.pointer<len(self.text):
                if not self.text[self.pointer].isdigit():
                    end=self.pointer
                    address=int(self.text[start:end])
                    if address==0:  # a line number address must be positive
                        self.invalid()
                    break
                self.pointer+=1
            else:
                self.invalid()
            return (atype,address)
        elif char=='/':
            self.pointer+=1
            atype='regex'
            start=self.pointer
            self.pointer+=1
            while self.pointer<len(self.text):
                if self.text[self.pointer]=='/':
                    end=self.pointer
                    address=self.text[start:end]
                    self.pointer+=1
                    break
                self.pointer+=1
            else:
                self.invalid()
        return (atype,address)

    def parse(self)->Command:
        """Parse one address (or range) and the command that follows it."""
        atype,address=self.parse_address()
        patype,padress=None,None
        additional=None

        self.delspace()
        if atype is not None and self.pointer<len(self.text) and self.text[self.pointer]==',':
            self.pointer+=1
            self.delspace()
            patype,padress=self.parse_address()
            if patype is None:
                self.invalid()

        self.delspace()
        if self.pointer==len(self.text):
            self.invalid()
        ctype=self.text[self.pointer]
        self.pointer+=1
        if ctype not in COMMANDS:
            self.invalid()
        if ctype=='q' and patype is not None:  # q can not take a range
            self.invalid()
        if ctype==':' and atype is not None:  # a label can not have an address
            self.invalid()

        if ctype=='s':
            # The character after the s is the delimiter, whatever it is.
            symbol=self.text[self.pointer]
            self.pointer+=1
            spattern=self.read_delimited(symbol)
            if spattern=='':  # the regex of an s command can not be empty
                self.invalid()
            sreplace=self.read_delimited(symbol)
            mchar=''  # g is the only permitted modifier
            if self.pointer<len(self.text) and self.text[self.pointer]=='g':
                mchar='g'
                self.pointer+=1
            additional=(spattern,sreplace,mchar)
            try:
                groups=re.compile(spattern).groups
            except re.error:
                self.invalid()
            for i in range(len(sreplace)-1):  # no back reference to a missing group
                if sreplace[i]=='\\' and sreplace[i+1].isdigit():
                    if int(sreplace[i+1])>groups:
                        self.invalid()

        elif ctype in ('a','i','c'):
            self.delspace()
            if self.pointer<len(self.text) and self.text[self.pointer]=='\\':
                self.pointer+=1
            additional=self.read_text()
            if additional=='':  # a, i and c need some text to add
                self.invalid()
        elif ctype in (':','b','t'):
            self.delspace()
            additional=self.read_label()

        # A command has to end here: the next thing must be a separator.
        if self.pointer<len(self.text):
            if self.text[self.pointer] not in (' ','\t','\n',';','#'):
                self.invalid()

        return Command(ctype,atype,address,patype=patype,padress=padress,additional=additional)

    def read_delimited(self,delimiter:str):
        """Read up to the next unescaped delimiter, returning the text before it."""
        cache=''
        while self.pointer<len(self.text):
            char=self.text[self.pointer]
            if char=='\\' and self.pointer+1<len(self.text):
                # An escaped delimiter is literal; other backslashes are kept.
                nxt=self.text[self.pointer+1]
                cache+=nxt if nxt==delimiter else (char+nxt)
                self.pointer+=2
            elif char==delimiter:
                self.pointer+=1
                return cache
            else:
                cache+=char
                self.pointer+=1
        else:
            self.invalid()

    def read_text(self):
        """Read the text of an a/i/c command: the rest of the line."""
        start=self.pointer
        while self.pointer<len(self.text) and self.text[self.pointer]!='\n':
            self.pointer+=1
        return self.text[start:self.pointer]

    def read_label(self):
        """Read the label of a :/b/t command, which may be empty."""
        start=self.pointer
        while self.pointer<len(self.text) and self.text[self.pointer] not in (';','\n','#'):
            self.pointer+=1
        label=self.text[start:self.pointer].strip()
        if len(label.split())>1:  # a label is a single word
            self.invalid()
        return label

def expand(match,repl:str):
    """Build the replacement text: \\1 to \\9 are groups, & is the whole match."""
    out=[]
    i=0
    while i<len(repl):
        char=repl[i]
        if char=='\\' and i+1<len(repl):
            following=repl[i+1]
            if following.isdigit():
                out.append(match.group(int(following)) or '')
            elif following=='n':
                out.append('\n')
            elif following=='t':
                out.append('\t')
            else:  # any other escape is just the character itself
                out.append(following)
            i+=2
        elif char=='&':
            out.append(match.group(0))
            i+=1
        else:
            out.append(char)
            i+=1
    return ''.join(out)

def substitute(pattern:str,repl:str,text:str,replace_all:bool):
    """Replace like sed, where an empty match right after a match does not count."""
    regex=re.compile(pattern)
    out=[]
    pos=0
    previous_end=-1
    count=0
    while pos<=len(text):
        match=regex.search(text,pos)
        if match is None:
            break
        start,end=match.span()
        if start==end and start==previous_end:  # empty match, skip one character
            if start>=len(text):
                break
            out.append(text[pos:start+1])
            pos=start+1
            continue
        out.append(text[pos:start])
        out.append(expand(match,repl))
        count+=1
        previous_end=end
        if start==end:
            pos=start
            if start>=len(text):
                break
            out.append(text[start])
            pos=start+1
        else:
            pos=end
        if not replace_all:
            break
    out.append(text[pos:])
    return ''.join(out),count

def match_address(atype:str,address:str,linenum:int,line:str,islast:bool):
    if atype=='digit':return linenum==address
    if atype=='regex':return re.search(address,line) is not None
    if atype=='dollar':return islast
    return False

def applies(command,linenum,line,islast):
    """Does this command apply to the current line?  Updates the range state."""
    if command.atype is None:  # no address: every line
        return True
    if command.patype is None:  # a single address
        return match_address(command.atype,command.address,linenum,line,islast)

    # A range runs from the first address to the second, and may open again.
    if command.inrange:
        if command.patype=='digit':
            if linenum>=command.padress:
                command.inrange=False
        elif match_address(command.patype,command.padress,linenum,line,islast):
            command.inrange=False
        return True

    if not match_address(command.atype,command.address,linenum,line,islast):
        return False
    command.inrange=True
    # An end line number already passed gives a one line range.  An end regex
    # is deliberately not tested here, only on later lines.
    if command.patype=='digit' and linenum>=command.padress:
        command.inrange=False
    elif command.patype=='dollar' and islast:
        command.inrange=False
    return True

def execute(commands:list,lines:tuple,mode_n:bool,out:object):
    """Apply the commands to every line.  Returns True if q was executed."""
    labels=find_labels(commands)
    linenum=1
    for line,islast in lines:
        deleted=False
        quitting=False
        appended=[]
        substituted=False
        # Driven by an index rather than a for loop, because b and t jump.
        stopped=False
        index=0
        while index<len(commands):
            command=commands[index]
            index+=1
            # Addresses are matched for every command even after d or q ended
            # the line, so that range states stay in step.
            matched=applies(command,linenum,line,islast)
            if stopped or not matched:
                continue
            if command.ctype=='q':
                quitting=True
                stopped=True
            elif command.ctype=='p':
                out.write(line+'\n')
            elif command.ctype=='d':
                deleted=True
                stopped=True
            elif command.ctype=='s':
                spattern,sreplace,mchar=command.additional
                line,n=substitute(spattern,sreplace,line,mchar=='g')
                if n:
                    substituted=True
            elif command.ctype=='i':
                out.write(command.additional+'\n')
            elif command.ctype=='a':
                appended.append(command.additional)
            elif command.ctype=='c':
                # Over a range the text is printed once, where the range ends.
                if command.patype is None or not command.inrange:
                    out.write(command.additional+'\n')
                deleted=True
                stopped=True
            elif command.ctype==':':
                pass
            elif command.ctype=='b':
                index=labels[command.additional] if command.additional else len(commands)
            elif command.ctype=='t':
                if substituted:
                    substituted=False  # cleared whenever t branches
                    index=labels[command.additional] if command.additional else len(commands)

        if not mode_n and not deleted:
            out.write(line+'\n')
        # Appended text is flushed even when the line itself was deleted.
        for text in appended:
            out.write(text+'\n')
        if quitting:
            return True
        linenum+=1
    return False

def readf(files):
    """Yield the input lines without their newline, from the files or stdin."""
    if not files:
        for line in sys.stdin:
            yield line.rstrip('\n')
        return

    for file in files:
        try:
            inputf=open(file)
        except OSError:  # carry on with the other files, report at the end
            global failed
            failed=True
            continue
        with inputf:
            for line in inputf:
                yield line.rstrip('\n')

def find_labels(commands)->dict:
    """Map each label name to its position in the command list."""
    d={}
    for i,c in enumerate(commands):
        if c.ctype==':':
            d[c.additional]=i
    return d

def preread(lines):
    """Yield (line, is_last_line) by holding one line back as look-ahead."""
    prev=None
    for line in lines:
        if prev is not None:
            yield (prev,False)
        prev=line
    if prev is not None:
        yield (prev,True)

def terminate(message='error'):
    sys.stdout.flush()  # so the message follows the output it belongs after
    print(f"{PROGRAM}: {message}",file=sys.stderr)
    sys.exit(1)

def usage():
    print(f"usage: {PROGRAM} "
          "[-i] [-n] [-f <script-file> | <sed-command>] [<files>...]",file=sys.stderr)
    sys.exit(1)

def main():
    args=sys.argv[1:]
    if not args:
        usage()

    mode_n,mode_i=False,False
    ftext=None
    fname=None
    while args:
        if not re.match(r'^-.+$',args[0]):
            break
        elif args[0]=='-n':
            mode_n=True
            del args[0]
        elif args[0]=='-f':
            try:
                fname=args[1]
                with open(args[1]) as f:
                    ftext=f.read()
                del args[0:2]
            except IndexError:
                usage()
            except FileNotFoundError:
                terminate()
        elif args[0]=='-i':
            mode_i=True
            del args[0]
        else:
            usage()
    if ftext is not None:  # with -f everything left is an input file
        script=ftext
        files=args
    else:  # without -f the first argument is the script
        if not args:
            terminate()
        script=args[0]
        files=args[1:]

    if script[:2]=='#n' and script[2:3] in ('','\n'):  # #n on line 1 means -n
        mode_n=True

    parser=Parser(script,fname)
    commands=parser.multiparse()
    labels=find_labels(commands)
    for command in commands:  # b and t must name a label that exists
        if command.ctype in ('b','t') and command.additional:
            if command.additional not in labels:
                terminate()
    if mode_i:
        if not files:  # -i has nothing to edit without a file
            usage()
        # With -i each file is edited on its own: line numbers restart.
        for filename in files:
            for command in commands:
                command.inrange=False  # ranges must not carry over between files
            # The temporary file goes in the same directory as the original
            # thus os.replace cannot fail across file systems.
            tmp=tempfile.NamedTemporaryFile('w',dir=os.path.dirname(filename) or '.',delete=False)
            with tmp:
                stopped=execute(commands,preread(readf([filename])),mode_n,tmp)
            os.replace(tmp.name,filename)
            if stopped:
                break
    else:
        execute(commands,preread(readf(files)),mode_n,sys.stdout)
    if failed:  # a file could not be opened earlier
        terminate()

if __name__=='__main__':
    main()
