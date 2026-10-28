import re
import numpy as np

fp = open(r"C:\Program Files\Micro-Manager-1.4\MMCorePy.py")

commands = []
returns = []
args = []
arg_names = []
start = False
counter = -1
for line in fp.readlines():
    line = line.strip()
    if line == "class CMMCore(_object):":
        start = True
        continue
    if line == "CMMCore_swigregister = _MMCorePy.CMMCore_swigregister":
        break
    if counter >= 0:
        counter += 1
    if counter == 1:
        if line != "\"\"\"":
            counter = -1
    if counter == 2:
        if line.find("->") != -1 or 1:
            match = re.match(r"(?P<name>\w*)\(self(?P<args>[\w ,]*)\)\s*(->)?\s*(?P<return>[\w ]*)?$", line)
            if match:
                dict = match.groupdict()
                commands.append(dict["name"])
                returns.append(dict["return"])
                new_args = []
                new_arg_names = []
                for arg in dict["args"][2:].split(", "):
                    if len(arg):
                        arg_name = arg[::-1].split(" ",1)[0][::-1]
                        arg = arg[::-1].split(" ",1)[1][::-1]
                        if arg == "unsigned int" or arg == "unsigned long" or arg == "int" or arg == "long":
                            arg = "int"
                        elif arg == "double":
                            arg = "float"
                        elif arg == "char" or arg == "unsigned char":
                            arg = "str"
                        elif arg == "bool":
                            arg = "bool"
                        else:
                            arg = "str"
                            #arg = "mmc."+arg
                        new_args.append(arg)
                        new_arg_names.append(arg_name)
                    else:
                        pass
                args.append(new_args)
                arg_names.append(new_arg_names)
                print line
            else:
                print "----------"+ line
        counter = -1
    if start and line[:4] == "def ":
        counter = 0
        continue
        match = re.match(r"def ([\w]*)\(", line)
        if match:
            function_name = match.groups()[0]
            if function_name[0] == "_":
                continue
            print "def "+function_name+"(*args,**kwargs): return AskServer('"+function_name+"',args,kwargs)"
        else:
            print line
    
#print "commandNames = "+str(commands)
#print "commands = "+str(['mmc.'+command for command in commands]).replace("'","")
#print "arguments = "+str(args).replace("'","")

for i in range(len(commands)):
    command =  "AskServer('Camera', %s)" % (", ".join(["'"+commands[i]+"'"]+arg_names[i]))
    print "def "+commands[i]+"("+", ".join(arg_names[i])+"): return "+command
    #print "def "+commands[i]+"("+", ".join(arg_names[i])+"): return AskServer('"+commands[i]+"".join(["str("+a+")" for a in arg_names[i]])+')'

fp = open(r"microscope.py")

commands = []
start = False
for line in fp.readlines():
    line = line.strip()
    if line == "class microscope:":
        start = True
        continue
    if start and line[:4] == "def ":
        match = re.match(r"def ([\w]*)\(self(.*)\):", line)
        if match:
            function_name = match.groups()[0]
            if function_name in ["open","close","isOpen","write","read"]:
                continue
            commands.append(function_name)
            args = match.groups()[1]
            if function_name[0] == "_":
                continue
            print "def "+function_name+"("+args[1:]+"): return AskServer('Microscope', '"+function_name+"'"+args+")"
        else:
            print line

print "commandNames = "+str(commands)
print "commands = "+str(['mic.'+command for command in commands]).replace("'","")