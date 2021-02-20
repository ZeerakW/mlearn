from libcpp.map cimport map
from libcpp.string cimport string
from libcpp.vector cimport vector
from cython.operator cimport dereference, preincrement

def f():
    my_dict = {'a':[1,2,3], 'b':[4,5] , 'c':[7,1,2]}
    # the following conversion has an computational cost to it 
    # and must be done with the GIL. Depending on your design
    # you might be able to ensure it's only done once so that the
    # cost doesn't matter much
    cdef map[string,int] m



    # cdef statements can't go inside no gil, but much of the work can
    cdef map[string,int].iterator end = m.end()
    cdef map[string,int].iterator it = m.begin()

    cdef int total_length = 0

    with nogil: # all  this stuff can now go inside nogil   
        while it != end:
            total_length += dereference(it).second.size()
            preincrement(it)

    print total_length

cdef class S2I_Dict:

    cdef unordered_map[string, int] mapa

    def __init__():
