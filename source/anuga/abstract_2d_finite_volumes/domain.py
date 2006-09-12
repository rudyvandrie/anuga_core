"""Class Domain - 2D triangular domains for finite-volume computations of
   conservation laws.


   Copyright 2004
   Ole Nielsen, Stephen Roberts, Duncan Gray, Christopher Zoppou
   Geoscience Australia
"""

from anuga.abstract_2d_finite_volumes.neighbour_mesh import Mesh
from anuga.abstract_2d_finite_volumes.generic_boundary_conditions\
     import Boundary
from anuga.abstract_2d_finite_volumes.generic_boundary_conditions\
     import File_boundary
from anuga.abstract_2d_finite_volumes.generic_boundary_conditions\
     import Dirichlet_boundary
from anuga.abstract_2d_finite_volumes.generic_boundary_conditions\
     import Time_boundary
from anuga.abstract_2d_finite_volumes.generic_boundary_conditions\
     import Transmissive_boundary

from anuga.abstract_2d_finite_volumes.pmesh2domain import pmesh_to_domain
from anuga.abstract_2d_finite_volumes.region\
     import Set_region as region_set_region

import types

class Domain(Mesh):


    def __init__(self,
                 source=None,
                 triangles=None,
                 boundary=None,
                 conserved_quantities=None,
                 other_quantities=None,
                 tagged_elements=None,
                 geo_reference=None,
                 use_inscribed_circle=False,
                 mesh_filename=None,
                 use_cache=False,
                 verbose=False,
                 full_send_dict=None,
                 ghost_recv_dict=None,
                 processor=0,
                 numproc=1):


        """Instantiate generic computational Domain.

        Input:
          source:    Either a mesh filename or coordinates of mesh vertices.
                     If it is a filename values specified for triangles will
                     be overridden.
          triangles: Mesh connectivity (see mesh.py for more information)
          boundary:  See mesh.py for more information

          conserved_quantities: List of quantity names entering the
                                conservation equations
          other_quantities:     List of other quantity names

          tagged_elements:
          ...


        """

        # Determine whether source is a mesh filename or coordinates
        if type(source) == types.StringType:
            mesh_filename = source
        else:
            coordinates = source


        # In case a filename has been specified, extract content
        if mesh_filename is not None:
            coordinates, triangles, boundary, vertex_quantity_dict, \
                         tagged_elements, geo_reference = \
                         pmesh_to_domain(file_name=mesh_filename,
                                         use_cache=use_cache,
                                         verbose=verbose)


        # Initialise underlying mesh structure
        Mesh.__init__(self, coordinates, triangles, boundary,
                      tagged_elements, geo_reference, use_inscribed_circle,
                      verbose=verbose)

        if verbose: print 'Initialising Domain'
        from Numeric import zeros, Float, Int, ones
        from quantity import Quantity, Conserved_quantity

        # List of quantity names entering
        # the conservation equations
        if conserved_quantities is None:
            self.conserved_quantities = []
        else:
            self.conserved_quantities = conserved_quantities

        # List of other quantity names
        if other_quantities is None:
            self.other_quantities = []
        else:
            self.other_quantities = other_quantities


        #Build dictionary of Quantity instances keyed by quantity names
        self.quantities = {}

        #FIXME: remove later - maybe OK, though....
        for name in self.conserved_quantities:
            self.quantities[name] = Conserved_quantity(self)
        for name in self.other_quantities:
            self.quantities[name] = Quantity(self)

        #Create an empty list for explicit forcing terms
        self.forcing_terms = []

        #Setup the ghost cell communication
        if full_send_dict is None:
            self.full_send_dict = {}
        else:
            self.full_send_dict  = full_send_dict

        # List of other quantity names
        if ghost_recv_dict  is None:
            self.ghost_recv_dict  = {}
        else:
            self.ghost_recv_dict  = ghost_recv_dict

        self.processor = processor
        self.numproc   = numproc

        # Setup Communication Buffers

        if verbose: print 'Domain: Set up communication buffers (parallel)'
        self.nsys = len(self.conserved_quantities)
        for key in self.full_send_dict:
            buffer_shape = self.full_send_dict[key][0].shape[0]
            self.full_send_dict[key].append(zeros( (buffer_shape,self.nsys) ,Float))


        for key in self.ghost_recv_dict:
            buffer_shape = self.ghost_recv_dict[key][0].shape[0]
            self.ghost_recv_dict[key].append(zeros( (buffer_shape,self.nsys) ,Float))


        # Setup cell full flag
        # =1 for full
        # =0 for ghost
        N=self.number_of_elements
        self.tri_full_flag = ones(N, Int)
        for i in self.ghost_recv_dict.keys():
            for id in self.ghost_recv_dict[i][0]:
                self.tri_full_flag[id] = 0


        #Defaults
        from anuga.config import max_smallsteps, beta_w, beta_h, epsilon, CFL
        self.beta_w = beta_w
        self.beta_h = beta_h
        self.epsilon = epsilon

        #FIXME: Maybe have separate orders for h-limiter and w-limiter?
        #Or maybe get rid of order altogether and use beta_w and beta_h
        self.set_default_order(1)
        #self.default_order = 1
        #self.order = self.default_order

        self.smallsteps = 0
        self.max_smallsteps = max_smallsteps
        self.number_of_steps = 0
        self.number_of_first_order_steps = 0
        self.CFL = CFL

        #Model time
        self.time = 0.0
        self.finaltime = None
        self.min_timestep = self.max_timestep = 0.0
        self.starttime = 0 #Physical starttime if any (0 is 1 Jan 1970 00:00:00)

        ######OBSOLETE
        #Origin in UTM coordinates
        #FIXME: This should be set if read by a msh file
        #self.zone = zone
        #self.xllcorner = xllcorner
        #self.yllcorner = yllcorner


        #Checkpointing and storage
        from anuga.config import default_datadir
        self.datadir = default_datadir
        self.filename = 'domain'
        self.checkpoint = False

        #MH310505 To avoid calculating the flux across each edge twice, keep an integer (boolean) array,
        #to be used during the flux calculation
        N=self.number_of_elements
        self.already_computed_flux = zeros((N, 3), Int)

        if mesh_filename is not None:
            # If the mesh file passed any quantity values
            # , initialise with these values.
            if verbose: print 'Domain: Initialising quantity values'
            self.set_quantity_vertices_dict(vertex_quantity_dict)


        if verbose: print 'Domain: Done'




    def set_default_order(self, n):
        """Set default (spatial) order to either 1 or 2
        """

        msg = 'Default order must be either 1 or 2. I got %s' %n
        assert n in [1,2], msg

        self.default_order = n
        self.order = self.default_order


    #Public interface to Domain
    def get_conserved_quantities(self, vol_id, vertex=None, edge=None):
        """Get conserved quantities at volume vol_id

        If vertex is specified use it as index for vertex values
        If edge is specified use it as index for edge values
        If neither are specified use centroid values
        If both are specified an exeception is raised

        Return value: Vector of length == number_of_conserved quantities

        """

        from Numeric import zeros, Float

        if not (vertex is None or edge is None):
            msg = 'Values for both vertex and edge was specified.'
            msg += 'Only one (or none) is allowed.'
            raise msg

        q = zeros( len(self.conserved_quantities), Float)

        for i, name in enumerate(self.conserved_quantities):
            Q = self.quantities[name]
            if vertex is not None:
                q[i] = Q.vertex_values[vol_id, vertex]
            elif edge is not None:
                q[i] = Q.edge_values[vol_id, edge]
            else:
                q[i] = Q.centroid_values[vol_id]

        return q

    def set_time(self, time=0.0):
        """Set the model time (seconds)"""

        self.time = time

    def set_quantity_vertices_dict(self, quantity_dict):
        """Set values for named quantities.
        The index is the quantity

        name: Name of quantity
        X: Compatible list, Numeric array, const or function (see below)

        The values will be stored in elements following their
        internal ordering.

        """
        for key in quantity_dict.keys():
            self.set_quantity(key, quantity_dict[key], location='vertices')


    def set_quantity(self, name, *args, **kwargs):
        """Set values for named quantity


        One keyword argument is documented here:
        expression = None, # Arbitrary expression

        expression:
          Arbitrary expression involving quantity names

        See Quantity.set_values for further documentation.
        """

        #FIXME (Ole): Allow new quantities here
        #from quantity import Quantity, Conserved_quantity
        #Create appropriate quantity object
        ##if name in self.conserved_quantities:
        ##    self.quantities[name] = Conserved_quantity(self)
        ##else:
        ##    self.quantities[name] = Quantity(self)


        #Do the expression stuff
        if kwargs.has_key('expression'):
            expression = kwargs['expression']
            del kwargs['expression']

            Q = self.create_quantity_from_expression(expression)
            kwargs['quantity'] = Q

        #Assign values
        self.quantities[name].set_values(*args, **kwargs)


    def get_quantity(self, name, location='vertices', indices = None):
        """Get quantity object.

        name: Name of quantity

        See methods inside the quantity object for more options
        """

        return self.quantities[name] #.get_values( location, indices = indices)


    def get_quantity_object(self, name):
        """Get object for named quantity

        name: Name of quantity

        FIXME: Obsolete
        """

        print 'get_quantity_object has been deprecated. Please use get_quantity'
        return self.quantities[name]


    def create_quantity_from_expression(self, expression):
        """Create new quantity from other quantities using arbitrary expression

        Combine existing quantities in domain using expression and return
        result as a new quantity.

        Note, the new quantity could e.g. be used in set_quantity

        Valid expressions are limited to operators defined in class Quantity

        Example:


        """

        from anuga.abstract_2d_finite_volumes.util import apply_expression_to_dictionary
        return apply_expression_to_dictionary(expression, self.quantities)




    def set_boundary(self, boundary_map):
        """Associate boundary objects with tagged boundary segments.

        Input boundary_map is a dictionary of boundary objects keyed
        by symbolic tags to matched against tags in the internal dictionary
        self.boundary.

        As result one pointer to a boundary object is stored for each vertex
        in the list self.boundary_objects.
        More entries may point to the same boundary object

        Schematically the mapping is from two dictionaries to one list
        where the index is used as pointer to the boundary_values arrays
        within each quantity.

        self.boundary:          (vol_id, edge_id): tag
        boundary_map (input):   tag: boundary_object
        ----------------------------------------------
        self.boundary_objects:  ((vol_id, edge_id), boundary_object)


        Pre-condition:
          self.boundary has been built.

        Post-condition:
          self.boundary_objects is built

        If a tag from the domain doesn't appear in the input dictionary an
        exception is raised.
        However, if a tag is not used to the domain, no error is thrown.
        FIXME: This would lead to implementation of a
        default boundary condition

        Note: If a segment is listed in the boundary dictionary and if it is
        not None, it *will* become a boundary -
        even if there is a neighbouring triangle.
        This would be the case for internal boundaries

        Boundary objects that are None will be skipped.

        FIXME: If set_boundary is called multiple times and if Boundary
        object is changed into None, the neighbour structure will not be
        restored!!!


        """

        self.boundary_objects = []
        self.boundary_map = boundary_map  #Store for use with eg. boundary_stats.

        #FIXME: Try to remove the sorting and fix test_mesh.py
        x = self.boundary.keys()
        x.sort()

        #Loop through edges that lie on the boundary and associate them with
        #callable boundary objects depending on their tags
        for k, (vol_id, edge_id) in enumerate(x):
            tag = self.boundary[ (vol_id, edge_id) ]

            if boundary_map.has_key(tag):
                B = boundary_map[tag]  #Get callable boundary object

                if B is not None:
                    self.boundary_objects.append( ((vol_id, edge_id), B) )
                    self.neighbours[vol_id, edge_id] = -len(self.boundary_objects)
                else:
                    pass
                    #FIXME: Check and perhaps fix neighbour structure


            else:
                msg = 'ERROR (domain.py): Tag "%s" has not been ' %tag
                msg += 'bound to a boundary object.\n'
                msg += 'All boundary tags defined in domain must appear '
                msg += 'in the supplied dictionary.\n'
                msg += 'The tags are: %s' %self.get_boundary_tags()
                raise msg


    def set_region(self, *args, **kwargs):
        """
        This method is used to set quantities based on a regional tag.
        
        It is most often called with the following parameters;
        (self, tag, quantity, X, location='vertices')
        tag: the name of the regional tag used to specify the region 
        quantity: Name of quantity to change
        X: const or function - how the quantity is changed
        location: Where values are to be stored.
            Permissible options are: vertices, centroid and unique vertices

        A callable region class or a list of callable region classes
        can also be passed into this function.
        """
        #print "*args", args
        #print "**kwargs", kwargs 
        if len(args) == 1:
            self._set_region(*args, **kwargs)
        else:
            #Assume it is arguments for the region.set_region function
            func = region_set_region(*args, **kwargs)
            self._set_region(func)
            
        
    def _set_region(self, functions):
        # The order of functions in the list is used.
        if type(functions) not in [types.ListType,types.TupleType]:
            functions = [functions]
        for function in functions:
            for tag in self.tagged_elements.keys():
                function(tag, self.tagged_elements[tag], self)


    #MISC
    def check_integrity(self):
        Mesh.check_integrity(self)

        for quantity in self.conserved_quantities:
            msg = 'Conserved quantities must be a subset of all quantities'
            assert quantity in self.quantities, msg

        ##assert hasattr(self, 'boundary_objects')

    def write_time(self):
        print self.timestepping_statistics()

        #Old version
        #if self.min_timestep == self.max_timestep:
        #    print 'Time = %.4f, delta t = %.8f, steps=%d (%d)'\
        #          %(self.time, self.min_timestep, self.number_of_steps,
        #            self.number_of_first_order_steps)
        #elif self.min_timestep > self.max_timestep:
        #    print 'Time = %.4f, steps=%d (%d)'\
        #          %(self.time, self.number_of_steps,
        #            self.number_of_first_order_steps)
        #else:
        #    print 'Time = %.4f, delta t in [%.8f, %.8f], steps=%d (%d)'\
        #          %(self.time, self.min_timestep,
        #            self.max_timestep, self.number_of_steps,
        #            self.number_of_first_order_steps)

    def timestepping_statistics(self):
        """Return string with time stepping statistics for printing or logging
        """

        msg = ''
        if self.min_timestep == self.max_timestep:
            msg += 'Time = %.4f, delta t = %.8f, steps=%d (%d)'\
                   %(self.time, self.min_timestep, self.number_of_steps,
                     self.number_of_first_order_steps)
        elif self.min_timestep > self.max_timestep:
            msg += 'Time = %.4f, steps=%d (%d)'\
                   %(self.time, self.number_of_steps,
                     self.number_of_first_order_steps)
        else:
            msg += 'Time = %.4f, delta t in [%.8f, %.8f], steps=%d (%d)'\
                   %(self.time, self.min_timestep,
                     self.max_timestep, self.number_of_steps,
                     self.number_of_first_order_steps)

        return msg


    def write_boundary_statistics(self, quantities = None, tags = None):
        print self.boundary_statistics(quantities, tags)

    def boundary_statistics(self, quantities = None, tags = None):
        """Output statistics about boundary forcing at each timestep


        Input:
          quantities: either None, a string or a list of strings naming the quantities to be reported
          tags:       either None, a string or a list of strings naming the tags to be reported


        Example output:
        Tag 'wall':
            stage in [2, 5.5]
            xmomentum in []
            ymomentum in []
        Tag 'ocean'


        If quantities are specified only report on those. Otherwise take all conserved quantities.
        If tags are specified only report on those, otherwise take all tags.

        """

        #Input checks
        import types, string

        if quantities is None:
            quantities = self.conserved_quantities
        elif type(quantities) == types.StringType:
            quantities = [quantities] #Turn it into a list

        msg = 'Keyword argument quantities must be either None, '
        msg += 'string or list. I got %s' %str(quantities)
        assert type(quantities) == types.ListType, msg


        if tags is None:
            tags = self.get_boundary_tags()
        elif type(tags) == types.StringType:
            tags = [tags] #Turn it into a list

        msg = 'Keyword argument tags must be either None, '
        msg += 'string or list. I got %s' %str(tags)
        assert type(tags) == types.ListType, msg

        #Determine width of longest quantity name (for cosmetic purposes)
        maxwidth = 0
        for name in quantities:
            w = len(name)
            if w > maxwidth:
                maxwidth = w

        #Output stats
        msg = 'Boundary values at time %.4f:\n' %self.time
        for tag in tags:
            msg += '    %s:\n' %tag

            for name in quantities:
                q = self.quantities[name]

                #Find range of boundary values for tag and q
                maxval = minval = None
                for i, ((vol_id, edge_id), B) in\
                        enumerate(self.boundary_objects):
                    if self.boundary[(vol_id, edge_id)] == tag:
                        v = q.boundary_values[i]
                        if minval is None or v < minval: minval = v
                        if maxval is None or v > maxval: maxval = v

                if minval is None or maxval is None:
                    msg += '        Sorry no information available about' +\
                           ' tag %s and quantity %s\n' %(tag, name)
                else:
                    msg += '        %s in [%12.8f, %12.8f]\n'\
                           %(string.ljust(name, maxwidth), minval, maxval)


        return msg


    def get_name(self):
        return self.filename

    def set_name(self, name):
        self.filename = name

    def get_datadir(self):
        return self.datadir

    def set_datadir(self, name):
        self.datadir = name



    #def set_defaults(self):
    #    """Set default values for uninitialised quantities.
    #    Should be overridden or specialised by specific modules
    #    """#
    #
    #    for name in self.conserved_quantities + self.other_quantities:
    #        self.set_quantity(name, 0.0)


    ###########################
    #Main components of evolve

    def evolve(self,
               yieldstep = None,
               finaltime = None,
               duration = None,
               skip_initial_step = False):
        """Evolve model through time starting from self.starttime.


        yieldstep: Interval between yields where results are stored,
                   statistics written and domain inspected or
                   possibly modified. If omitted the internal predefined
                   max timestep is used.
                   Internally, smaller timesteps may be taken.

        duration: Duration of simulation

        finaltime: Time where simulation should end

        If both duration and finaltime are given an exception is thrown.


        skip_initial_step: Boolean flag that decides whether the first
        yield step is skipped or not. This is useful for example to avoid
        duplicate steps when multiple evolve processes are dove tailed.


        Evolve is implemented as a generator and is to be called as such, e.g.

        for t in domain.evolve(yieldstep, finaltime):
            <Do something with domain and t>


        All times are given in seconds

        """

        from anuga.config import min_timestep, max_timestep, epsilon

        #FIXME: Maybe lump into a larger check prior to evolving
        msg = 'Boundary tags must be bound to boundary objects before evolving system, '
        msg += 'e.g. using the method set_boundary.\n'
        msg += 'This system has the boundary tags %s '\
               %self.get_boundary_tags()
        assert hasattr(self, 'boundary_objects'), msg

        ##self.set_defaults()

        if yieldstep is None:
            yieldstep = max_timestep
        else:
            yieldstep = float(yieldstep)

        self.order = self.default_order


        if finaltime is not None and duration is not None:
            print 'F', finaltime, duration
            msg = 'Only one of finaltime and duration may be specified'
            raise msg
        else:
            if finaltime is not None:
                self.finaltime = float(finaltime)
            if duration is not None:
                self.finaltime = self.starttime + float(duration)




        self.yieldtime = 0.0 #Time between 'yields'

        #Initialise interval of timestep sizes (for reporting only)
        self.min_timestep = max_timestep
        self.max_timestep = min_timestep
        self.number_of_steps = 0
        self.number_of_first_order_steps = 0

        #update ghosts
        self.update_ghosts()

        #Initial update of vertex and edge values
        self.distribute_to_vertices_and_edges()

        #Initial update boundary values
        self.update_boundary()

        #Or maybe restore from latest checkpoint
        if self.checkpoint is True:
            self.goto_latest_checkpoint()

        if skip_initial_step is False:
            yield(self.time)  #Yield initial values

        while True:

            #Compute fluxes across each element edge
            self.compute_fluxes()

            #Update timestep to fit yieldstep and finaltime
            self.update_timestep(yieldstep, finaltime)

            #Update conserved quantities
            self.update_conserved_quantities()

            #update ghosts
            self.update_ghosts()

            #Update vertex and edge values
            self.distribute_to_vertices_and_edges()

            #Update boundary values
            self.update_boundary()

            #Update time
            self.time += self.timestep
            self.yieldtime += self.timestep
            self.number_of_steps += 1
            if self.order == 1:
                self.number_of_first_order_steps += 1

            #Yield results
	    if finaltime is not None and self.time >= finaltime:

		if self.time > finaltime:
  		    #FIXME (Ole, 30 April 2006): Do we need this check?
		    print 'WARNING (domain.py): time overshot finaltime. Contact Ole.Nielsen@ga.gov.au'
                    self.time = finaltime

                # Yield final time and stop
                yield(self.time)
                break


	    if self.yieldtime >= yieldstep:
                # Yield (intermediate) time and allow inspection of domain

                if self.checkpoint is True:
                    self.store_checkpoint()
                    self.delete_old_checkpoints()

                #Pass control on to outer loop for more specific actions
                yield(self.time)

                # Reinitialise
                self.yieldtime = 0.0
                self.min_timestep = max_timestep
                self.max_timestep = min_timestep
                self.number_of_steps = 0
                self.number_of_first_order_steps = 0


    def evolve_to_end(self, finaltime = 1.0):
        """Iterate evolve all the way to the end
        """

        for _ in self.evolve(yieldstep=None, finaltime=finaltime):
            pass



    def update_boundary(self):
        """Go through list of boundary objects and update boundary values
        for all conserved quantities on boundary.
        """

        #FIXME: Update only those that change (if that can be worked out)
        #FIXME: Boundary objects should not include ghost nodes.
        for i, ((vol_id, edge_id), B) in enumerate(self.boundary_objects):
	    if B is None:
	        print 'WARNING: Ignored boundary segment %d (None)'
	    else:
                q = B.evaluate(vol_id, edge_id)

                for j, name in enumerate(self.conserved_quantities):
                    Q = self.quantities[name]
                    Q.boundary_values[i] = q[j]


    def compute_fluxes(self):
        msg = 'Method compute_fluxes must be overridden by Domain subclass'
        raise msg


    def update_timestep(self, yieldstep, finaltime):

        from anuga.config import min_timestep, max_timestep

        # self.timestep is calculated from speed of characteristics
        # Apply CFL condition here
        timestep = min(self.CFL*self.timestep,max_timestep)

        #Record maximal and minimal values of timestep for reporting
        self.max_timestep = max(timestep, self.max_timestep)
        self.min_timestep = min(timestep, self.min_timestep)

        #Protect against degenerate time steps
        if timestep < min_timestep:

            #Number of consecutive small steps taken b4 taking action
            self.smallsteps += 1

            if self.smallsteps > self.max_smallsteps:
                self.smallsteps = 0 #Reset

                if self.order == 1:
                    msg = 'WARNING: Too small timestep %.16f reached '\
                          %timestep
                    msg += 'even after %d steps of 1 order scheme'\
                           %self.max_smallsteps
                    print msg
                    timestep = min_timestep  #Try enforcing min_step

                    #raise msg
                else:
                    #Try to overcome situation by switching to 1 order
                    self.order = 1

        else:
            self.smallsteps = 0
            if self.order == 1 and self.default_order == 2:
                self.order = 2


        #Ensure that final time is not exceeded
        if finaltime is not None and self.time + timestep > finaltime:
            timestep = finaltime-self.time

        #Ensure that model time is aligned with yieldsteps
        if self.yieldtime + timestep > yieldstep:
            timestep = yieldstep-self.yieldtime

        self.timestep = timestep



    def compute_forcing_terms(self):
        """If there are any forcing functions driving the system
        they should be defined in Domain subclass and appended to
        the list self.forcing_terms
        """

        for f in self.forcing_terms:
            f(self)



    def update_conserved_quantities(self):
        """Update vectors of conserved quantities using previously
        computed fluxes specified forcing functions.
        """

        from Numeric import ones, sum, equal, Float

        N = self.number_of_elements
        d = len(self.conserved_quantities)

        timestep = self.timestep

        #Compute forcing terms
        self.compute_forcing_terms()

        #Update conserved_quantities
        for name in self.conserved_quantities:
            Q = self.quantities[name]
            Q.update(timestep)

            #Clean up
            #Note that Q.explicit_update is reset by compute_fluxes

            #MH090605 commented out the following since semi_implicit_update is now re-initialized
            #at the end of the _update function in quantity_ext.c (This is called by the
            #preceeding Q.update(timestep) statement above).
            #For run_profile.py with N=128, the time of update_conserved_quantities is cut from 14.00 secs
            #to 8.35 secs

            #Q.semi_implicit_update[:] = 0.0

    def update_ghosts(self):
        pass

    def distribute_to_vertices_and_edges(self):
        """Extrapolate conserved quantities from centroid to
        vertices and edge-midpoints for each volume

        Default implementation is straight first order,
        i.e. constant values throughout each element and
        no reference to non-conserved quantities.
        """

        for name in self.conserved_quantities:
            Q = self.quantities[name]
            if self.order == 1:
                Q.extrapolate_first_order()
            elif self.order == 2:
                Q.extrapolate_second_order()
                Q.limit()
            else:
                raise 'Unknown order'
            Q.interpolate_from_vertices_to_edges()


    def centroid_norm(self, quantity, normfunc):
        """Calculate the norm of the centroid values
        of a specific quantity, using normfunc.

        normfunc should take a list to a float.

        common normfuncs are provided in the module utilities.norms
        """
        return normfunc(self.quantities[quantity].centroid_values)



##############################################
#Initialise module

#Optimisation with psyco
from anuga.config import use_psyco
if use_psyco:
    try:
        import psyco
    except:
        import os
        if os.name == 'posix' and os.uname()[4] == 'x86_64':
            pass
            #Psyco isn't supported on 64 bit systems, but it doesn't matter
        else:
            msg = 'WARNING: psyco (speedup) could not import'+\
                  ', you may want to consider installing it'
            print msg
    else:
        psyco.bind(Domain.update_boundary)
        #psyco.bind(Domain.update_timestep)     #Not worth it
        psyco.bind(Domain.update_conserved_quantities)
        psyco.bind(Domain.distribute_to_vertices_and_edges)


if __name__ == "__main__":
    pass
