import abc
from typing import List, Generic, TypeVar, Union, Optional

from data.graph import EdgeOutput, MessageOutput
from graph.edge import BaseEdge

NodeInput = TypeVar("NodeInput")

class BaseNode(abc.ABC, Generic[NodeInput]):

    def __init__(self, edges: Optional[List[BaseEdge]] = None, final_state=False):
        self._edges = edges
        self._node_input = None
        self._final_state = final_state

    def is_node_final(self):
        return self._final_state

    def set_node_input(self, edge_output: EdgeOutput):
        self._node_input = edge_output

    def run_to_continue(self, user_input: NodeInput) -> Optional[EdgeOutput]:
        res = None
        for edge in self._edges:
            res = edge.execute(user_input)
            if res is not None and res.should_continue:
                return res
        return res

    def execute(self, user_input: NodeInput) -> Union[MessageOutput, EdgeOutput]:
        res = self.run_to_continue(user_input)
        if res is None or not res.should_continue:
            return self.no_edges_found(user_input)
        else:
            if res.next_node is not None:
                res.next_node.set_node_input(res.result)

        return res

    @abc.abstractmethod
    def greeting_message(self) -> Optional[MessageOutput]:
        pass

    @abc.abstractmethod
    def no_edges_found(self, user_input: NodeInput) -> Optional[MessageOutput]:
        pass
