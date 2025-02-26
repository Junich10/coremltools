# -*- coding: utf-8 -*-
from __future__ import print_function as _
from __future__ import division as _
from __future__ import absolute_import as _
import copy

from .commons import builtins
from .commons.dot_visitor import DotVisitor
from .commons.basic_graph_ops import check_connections, const_determined_nodes


class ParsedNode(object):
    """
    Node class for the SSA graph.

    name: The name of the node (str)
    op: The operation represented by the node (str)
    datatype: The type of the node. (type)
    value: The value of the node if available 
    inputs: The list of nodes which are inputs to this node (list[str])
    control_inputs: The list of nodes which have to be executed before this node (list[str])
    attr: The attributes of the node
    outputs: The list of nodes which consume the result of this node (list[str])
    control_outputs: The list of nodes which have to be executed after this node (list[str])
    """
    __slots__ = [
        'name', 'op', 'datatype', 'value', 'inputs', 'control_inputs', 'outputs', 'control_outputs',
        'attr'
    ]

    def __init__(self):
        self.name = None
        self.op = None
        self.datatype = None
        self.value = None
        self.inputs = []
        self.outputs = []
        self.control_inputs = []
        self.control_outputs = []
        self.attr = {}

    def __copy__(self):
        ret = ParsedNode()
        ret.name = self.name
        ret.op = self.op
        ret.datatype = self.datatype
        ret.value = copy.deepcopy(self.value)
        ret.inputs = self.inputs[:]
        ret.control_inputs = self.control_inputs[:]
        ret.outputs = self.outputs[:]
        ret.control_outputs = self.control_outputs[:]
        ret.attr = {k: copy.deepcopy(v) for k, v in self.attr.items()}
        return ret

    def copy(self):
        return self.__copy__()


class SSAFunction(object):
    __slots__ = ["graph", "inputs", "input_types", "outputs", "output_types"]

    def __init__(self, gdict={}):
        self.graph = gdict
        self.inputs = []
        self.outputs = []
        self.input_types = []
        self.output_types = []
        check_connections(gdict)
        self.find_inputs_and_outputs()

    def find_inputs_and_outputs(self):
        # solve for input and output vars
        self.inputs = []
        self.outputs = []
        self.input_types = []
        self.output_types = []
        sorted_keys = sorted(self.graph.keys())

        # we use function entry and exit points if available
        # otherwise we find graph entry and exit points
        enters = [n.name for n in self.graph.values() if 'entry' in n.op]
        exits = [n.name for n in self.graph.values() if n.op == 'return']
        if len(enters) > 0 or len(exits) > 0:
            try:
                assert (len(enters) > 0)
                assert (len(exits) > 0)
            except:
                import pdb
                pdb.set_trace()
            self.inputs = enters
            self.input_types = [self.graph[v].datatype for v in self.inputs]
            self.outputs = exits
            self.output_types = [self.graph[v].datatype for v in self.outputs]
        else:
            for k in sorted_keys:
                v = self.graph[k]
                if len(v.inputs) == 0 and v.op not in ['Const', 'get_global', 'NoOp']:
                    self.inputs.append(k)
                    self.input_types.append(v.datatype)
                elif len(v.inputs) != 0 and v.op == "Placeholder":
                    assert len(v.inputs) == 1, "This is not a PlaceholderWithDefault!"
                    self.inputs.append(k)
                    self.input_types.append(v.datatype)
                if len(v.outputs) == 0 and v.op != "set_global":
                    self.outputs.append(k)
                    self.output_types.append(v.datatype)

    def __copy__(self):
        ret = SSAFunction()
        ret.inputs = self.inputs[:]
        ret.input_types = self.input_types[:]
        ret.outputs = self.outputs[:]
        ret.output_types = self.output_types[:]
        ret.graph = {k: copy.copy(v) for k, v in self.graph.items()}
        return ret

    def copy(self):
        return self.__copy__()


class NetworkEnsemble(object):
    __slots__ = ["functions", "variables", "global_resource"]

    def __init__(self, instance=None):
        self.functions = {}
        self.variables = {}
        self.global_resource = {}

        if isinstance(instance, NetworkEnsemble):
            self.functions = {k: copy.copy(v) for k, v in instance.functions.items()}
            self.variables = {k: copy.copy(v) for k, v in instance.variables.items()}
            self.global_resource = {k: copy.copy(v) for k, v in instance.global_resource.items()}

    def rename_function(self, src_func, tgt_func):
        """
        Renames the function with function name (src_func) to (tgt_func)
        """
        if src_func not in self.functions:
            print("Couldn't find function name (%s)." % (src_func))
            return
        if tgt_func in self.functions:
            print("(%s) already exists in some function name." % (tgt_func))
            return

        self.functions[tgt_func] = self.functions.pop(src_func)
        print("Successfully changed function name from (%s) to (%s)" % (src_func, tgt_func))

    def rename_node(self, src_node, tgt_node):
        """
        Rename the node with node name (src_node) to (tgt_node).
        Note that the name (tgt_node) cannot appear in the whole network,
        not only the function it lies in.
        """
        in_ssa = False
        success = None
        for func, ssa in self.functions.items():
            if src_node in ssa.graph:
                in_ssa = True
                if tgt_node in ssa.graph:
                    print("(%s) already exists in function (%s)." % (tgt_node, func))
                    break
                success = func
                ssa.graph[tgt_node] = ssa.graph.pop(src_node)
                # Replace other nodes' output dependency
                for inp in ssa.graph[tgt_node].inputs:
                    for idx, out in enumerate(ssa.graph[inp].outputs):
                        if out == src_node:
                            ssa.graph[inp].outputs[idx] = tgt_node
                            break
                # Replace other nodes' control output dependency
                for c_inp in ssa.graph[tgt_node].control_inputs:
                    for idx, c_out in enumerate(ssa.graph[c_inp].control_outputs):
                        if c_out == src_node:
                            ssa.graph[c_inp].control_outputs[idx] = tgt_node
                            break
                # Replace other nodes' input dependency
                for out in ssa.graph[tgt_node].outputs:
                    for idx, inp in enumerate(ssa.graph[out].inputs):
                        if inp == src_node:
                            ssa.graph[out].inputs[idx] = tgt_node
                            break
                # Replace other nodes' control input dependency
                for c_out in ssa.graph[tgt_node].control_outputs:
                    for idx, c_inp in enumerate(ssa.graph[c_out].control_inputs):
                        if c_inp == src_node:
                            ssa.graph[c_out].control_inputs[idx] = tgt_node
                            break
                break

        if not in_ssa:
            print("Couldn't find (%s) in any functions" % (src_node))
        if success is not None:
            print("Changed (%s) to (%s) in function (%s)" % (src_node, tgt_node, success))

    def extract_subgraph(self, outputs, target_inputs=None, name=""):
        """
        Given a list of outputs, determine which nodes are needed for      
        producing the outputs and build a new SSAFunction in the original
        NetworkEnsemble that would produce the target outputs.
        The function name for the new function would be concatenating all
        outputs together unless specified.
        """
        if not isinstance(outputs, list):
            print("Feed a list of output names for subgraph extraction.\nArgument is not a list.")
            return

        if name == "":
            outputs.sort()
            name = "_".join(outputs)

        if target_inputs is None:
            target_inputs = []

        def DFS_inputs(graph, node, vis):
            vis.add(node)
            if node in target_inputs:
                return [node]
            if (len(graph[node].inputs) == 0 and
                len(graph[node].control_inputs) == 0 and graph[node].op != "Const"):
                return [node]
            inputs = []
            for i in graph[node].inputs + graph[node].control_inputs:
                if i in vis:
                    continue
                inputs += DFS_inputs(graph, i, vis)
            return inputs

        def DFS_set_globals(graph, node, vis):
            vis.add(node)
            set_globals = []
            if graph[node].op == "set_global":
                set_globals.append(node)
            for i in graph[node].outputs + graph[node].control_outputs:
                if i in vis:
                    continue
                set_globals += DFS_set_globals(graph, i, vis)
            return set_globals

        for k in list(self.functions.keys()):
            v = self.functions[k]
            extract = []
            for output in outputs:
                if output in v.graph:
                    extract.append(output)

            if len(extract) == 0:
                continue
            incl_nodes = set()
            gdict = copy.deepcopy(v.graph)
            inputs = []
            set_globals = []
            for output in extract:
                inputs += DFS_inputs(gdict, output, incl_nodes)
            vis_nodes = set()
            for inp in inputs:
                set_globals += DFS_set_globals(gdict, inp, vis_nodes)
            for node in set_globals:
                inputs += DFS_inputs(gdict, node, incl_nodes)

            for new_k, new_v in v.graph.items():
                if new_k not in incl_nodes:
                    del gdict[new_k]
                    continue
                if new_k in target_inputs:
                    gdict[new_k].op = "Placeholder"
                gdict[new_k].inputs = [inp for inp in new_v.inputs if inp in incl_nodes]
                gdict[new_k].outputs = [out for out in new_v.outputs if out in incl_nodes]
                gdict[new_k].control_inputs = [
                    inp for inp in new_v.control_inputs if inp in incl_nodes
                ]
                gdict[new_k].control_outputs = [
                    out for out in new_v.control_outputs if out in incl_nodes
                ]

            for output in extract:
                old_name = "preIdentity_" + output
                output_node = copy.deepcopy(gdict[output])
                output_node.op = "Identity"
                output_node.inputs = [old_name]
                output_node.control_inputs = []
                output_node.outputs = []
                output_node.control_outputs = []

                for inp in gdict[output].inputs:
                    for idx, out in enumerate(gdict[inp].outputs):
                        if out == output:
                            gdict[inp].outputs[idx] = old_name
                for inp in gdict[output].control_inputs:
                    for idx, out in enumerate(gdict[inp].control_outputs):
                        if out == output:
                            gdict[inp].control_outputs[idx] = old_name
                for out in gdict[output].outputs:
                    for idx, inp in enumerate(gdict[out].inputs):
                        if inp == output:
                            gdict[out].inputs[idx] = old_name
                for out in gdict[output].control_outputs:
                    for idx, inp in enumerate(gdict[out].control_inputs):
                        if inp == output:
                            gdict[out].control_inputs[idx] = old_name
                gdict[output].outputs.append(output)
                gdict[output].name = old_name
                gdict[old_name] = gdict[output]
                gdict[output] = output_node

            self.functions[name] = SSAFunction(gdict)

    def delete_subgraph(self, name):
        """
        Delete the SSAfunction with function_name. 
        """
        if name not in self.functions:
            print("(%s) not in NetworkEnsemble" % (name))
            return
        del self.functions[name]

    def __repr__(self):
        return str(self)

    def __str__(self):
        ret = ""
        for func, v in self.functions.items():
            if func.startswith("body_function_") or func.startswith("f_body_function_"):
                continue
            elif func.startswith("cond_function_") or func.startswith("f_cond_function_"):
                continue

            ret += "Input Function Name: %s\n" % (func)
            ret += "  Inputs:\n"
            for inp in v.inputs:
                ret += "    %s\n" % (inp)
            ret += "  Outputs:\n"
            for out in v.outputs:
                if out.startswith('fake_exit_'):
                    continue
                ret += "    %s\n" % (out)
        return ret

    def get_dot_string(self, name_and_op_style=False, annotation=False):
        """
        Return the dot string that can be used to show the whole graph
        with dot. By default, the graph contains op and type. If 
        name_and_op_style is set, the graph will contain the name of the node
        and the op instead.

        * Input nodes : yellow
        * constant nodes : azure
        * output nodes : goldenrod2
        * nodes with variable shaped tensors : cyan

        Parameters
        ----------
        name_and_op_style: bool
            If set, graph contains only the name and the op.

        annotation: bool
        Examples
        --------
        >>> import graphviz
        >>> graphviz.Source(network.get_dot_string()).view()
        
        """
        function_names = sorted(self.functions.keys())

        dotstring = 'digraph g {\n' + \
                    '\tcompound=true;\n'
        # find all tensor nodes with unknown sizes
        ctr = 0
        for k in function_names:
            const_nodes = const_determined_nodes(self.functions[k].graph)
            unknown_sized_tensor_ops = []
            for v, n in self.functions[k].graph.items():
                if n.datatype is None or (n.datatype is not None and \
                        builtins.is_tensor(n.datatype) and \
                        (len(n.datatype.get_shape()) == 0 or -1 in n.datatype.get_shape())):
                    unknown_sized_tensor_ops.append(v)

            v = self.functions[k]
            vis = DotVisitor(annotation)
            vis.highlight_nodes(v.inputs, 'yellow') \
               .highlight_nodes(const_nodes, 'azure2') \
               .highlight_nodes(v.outputs,'goldenrod2') \
               .highlight_nodes(unknown_sized_tensor_ops,'cyan2')
            if name_and_op_style:
                vis.labeller(lambda n: n.name + ': ' + n.op)

            res = vis.visit_all(
                v.graph,
                nodename_prefix=str(ctr)).get_result('subgraph', 'cluster_' + k.replace('/', '_'))
            dotstring += '\n'.join('\t' + r for r in res.split('\n')) + "\n"
            ctr += 1
        dotstring += "}"
        return dotstring

    def add_function_with_prefix(self, fprefix, ssa):
        assert (isinstance(ssa, SSAFunction))
        s = 0
        while fprefix + str(s) in self.functions:
            s += 1
        self.functions[fprefix + str(s)] = ssa

    def add_function(self, f, ssa):
        self.functions[f] = ssa

    def __copy__(self):
        import copy
        ret = self.__class__()
        ret.functions = {k: copy.copy(v) for k, v in self.functions.items()}
        ret.variables = {k: copy.copy(v) for k, v in self.variables.items()}
        ret.global_resource = {k: copy.copy(v) for k, v in self.global_resource.items()}
        return ret

    def copy(self):
        return self.__copy__()

    def _find_free_name(self, prefix):
        idx = 0
        while (True):
            name = prefix + str(idx)
            found = False
            for v in self.functions.values():
                if name in v.graph:
                    found = True
                    break
            if found:
                idx += 1
            else:
                return name
