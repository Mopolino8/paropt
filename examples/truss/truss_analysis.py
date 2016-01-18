# Import numpy 
import numpy as np

# Import parts of matplotlib for plotting
import matplotlib.pyplot as plt
import matplotlib.colors as colors
import matplotlib.cm as cmx

# Import MPI
from mpi4py import MPI

# Import ParOpt
from paropt import ParOpt

class TrussAnalysis(ParOpt.pyParOptProblem):
    def __init__(self, conn, xpos, loads, bcs, 
                 E, rho, m_fixed, A_min, A_max, A_init=None,
                 Area_scale=1e-3, mass_scale=None):
        '''
        Analysis problem for mass-constrained compliance minimization
        '''

        # Initialize the super class
        nvars = len(conn)
        ncon = 1
        super(TrussAnalysis, self).__init__(MPI.COMM_SELF, 
                                            nvars, ncon)

        # Store pointer to the data
        self.conn = conn
        self.xpos = xpos
        self.loads = loads
        self.bcs = bcs

        # Set the material properties
        self.E = E
        self.rho = rho

        # Fixed mass value
        self.m_fixed = m_fixed

        # Set the values for the scaling
        self.A_min = A_min
        self.A_max = A_max
        self.Area_scale = Area_scale

        if A_init is None:
            self.A_init = 0.5*(A_min + A_max)
        else:
            self.A_init = A_init

        # Scaling for the objective
        self.obj_scale = None

        # Scaling for the mass constraint
        if mass_scale is None:
            self.mass_scale = self.m_fixed/nvars
        else:
            self.mass_scale = mass_scale

        return

    def getVarsAndBounds(self, x, lb, ub):
        '''Get the variable values and bounds'''
        lb[:] = self.A_min/self.Area_scale
        ub[:] = self.A_max/self.Area_scale
        x[:] = self.A_init/self.Area_scale
        return

    def evalObjCon(self, x):
        '''
        Evaluate the objective (compliance) and constraint (mass)
        '''
        # Keep a pointer to the design vector
        self.x = x

        A = self.Area_scale*x

        # Evaluate compliance objective
        K = self.assembleMat(A)
        f = self.assembleLoadVec()
        self.applyBCs(K, f)

        # Solve the resulting linear system of equations
        u = np.linalg.solve(K, f)
        
        # Compute the compliance objective
        obj = 0.5*np.dot(u, f)
        if self.obj_scale is None:
            self.obj_scale = 1.0*obj

        # Scale the compliance objective
        obj = obj/self.obj_scale

        # Compute the mass of the entire truss
        mass = 0.0
        index = 0

        for bar in self.conn:
            # Get the first and second node numbers from the bar
            n1 = bar[0]
            n2 = bar[1]

            # Compute the nodal locations
            xd = self.xpos[2*n2] - self.xpos[2*n1]
            yd = self.xpos[2*n2+1] - self.xpos[2*n1+1]
            Le = np.sqrt(xd**2 + yd**2)
            mass += self.rho*Le*A[index]

            index += 1

        # Create the array of constraints >= 0.0
        con = np.array([self.m_fixed - mass])/self.mass_scale

        fail = 0
        return fail, obj, con

    def evalObjConGradient(self, x, gobj, Acon):
        '''
        Evaluate the derivative of the compliance and mass
        '''
        
        # Zero the objecive and constraint gradients
        gobj[:] = 0.0
        Acon[:] = 0.0

        # Retrieve the area variables
        A = self.Area_scale*x

        # Evaluate compliance objective
        K = self.assembleMat(A)
        f = self.assembleLoadVec()
        self.applyBCs(K, f)

        # Solve the resulting linear system of equations
        u = np.linalg.solve(K, f)
        
        # Add up the contribution to the gradient
        index = 0
        for bar, A_bar in zip(self.conn, A):
            # Get the first and second node numbers from the bar
            n1 = bar[0]
            n2 = bar[1]

            # Compute the nodal locations
            xd = self.xpos[2*n2] - self.xpos[2*n1]
            yd = self.xpos[2*n2+1] - self.xpos[2*n1+1]
            Le = np.sqrt(xd**2 + yd**2)
            C = xd/Le
            S = yd/Le
            
            # Add the contribution to the gradient of the mass
            Acon[0, index] += self.rho*Le

            # Compute the element stiffness matrix
            Ke = (self.E/Le)*np.array(
                [[C**2, C*S, -C**2, -C*S],
                 [C*S, S**2, -C*S, -S**2],
                 [-C**2, -C*S, C**2, C*S],
                 [-C*S, -S**2, C*S, S**2]])
            
            # Create a list of the element variables for convenience
            elem_vars = [2*n1, 2*n1+1, 2*n2, 2*n2+1]
            
            # Add the product to the derivative of the compliance
            for i in xrange(4):
                for j in xrange(4):
                    gobj[index] -= 0.5*u[elem_vars[i]]*u[elem_vars[j]]*Ke[i, j]
            
            index += 1

        # Create the array of constraints >= 0.0
        Acon[0, :] *= -self.Area_scale/self.mass_scale

        # Scale the objective gradient
        gobj *= self.Area_scale/self.obj_scale

        print 'max gobj, gcon', max(abs(gobj)), max(abs(Acon[0,:]))

        fail = 0
        return fail

    def evalHvecProduct(self, x, z, zw, px, hvec):
        '''
        Evaluate the product of the input vector px with the Hessian
        of the Lagrangian.
        '''
        
        # Zero the hessian-vector product
        hvec[:] = 0.0

        # Retrieve the area variables
        A = self.Area_scale*x

        # Evaluate compliance objective
        K = self.assembleMat(A)
        f = self.assembleLoadVec()
        self.applyBCs(K, f)

        # Solve the resulting linear system of equations
        u = np.linalg.solve(K, f)

        # Assemble the stiffness matrix along the px direction
        Kp = self.assembleMat(self.Area_scale*px)
        rp = np.dot(Kp, u)
        self.applyBCs(Kp, rp)

        # Solve for the vector phi
        phi = np.linalg.solve(K, rp)
        
        # Add up the contribution to the gradient
        index = 0
        for bar, A_bar in zip(self.conn, A):
            # Get the first and second node numbers from the bar
            n1 = bar[0]
            n2 = bar[1]

            # Compute the nodal locations
            xd = self.xpos[2*n2] - self.xpos[2*n1]
            yd = self.xpos[2*n2+1] - self.xpos[2*n1+1]
            Le = np.sqrt(xd**2 + yd**2)
            C = xd/Le
            S = yd/Le
            
            # Compute the element stiffness matrix
            Ke = (self.E/Le)*np.array(
                [[C**2, C*S, -C**2, -C*S],
                 [C*S, S**2, -C*S, -S**2],
                 [-C**2, -C*S, C**2, C*S],
                 [-C*S, -S**2, C*S, S**2]])
            
            # Create a list of the element variables for convenience
            elem_vars = [2*n1, 2*n1+1, 2*n2, 2*n2+1]
            
            # Add the product to the derivative of the compliance
            for i in xrange(4):
                for j in xrange(4):
                    hvec[index] += phi[elem_vars[i]]*u[elem_vars[j]]*Ke[i, j]
            
            index += 1

        hvec *= self.Area_scale**2/self.obj_scale

        fail = 0
        return fail

    def assembleMat(self, A):
        '''
        Given the connectivity, nodal locations and material properties,
        assemble the stiffness matrix
        
        input:
        A:   the bar area
        '''

        # Create the global stiffness matrix
        nvars = len(self.xpos)
        K = np.zeros((nvars, nvars))

        # Loop over each element in the mesh
        for bar, A_bar in zip(self.conn, A):
            # Get the first and second node numbers from the bar
            n1 = bar[0]
            n2 = bar[1]

            # Compute the nodal locations
            xd = self.xpos[2*n2] - self.xpos[2*n1]
            yd = self.xpos[2*n2+1] - self.xpos[2*n1+1]
            Le = np.sqrt(xd**2 + yd**2)
            C = xd/Le
            S = yd/Le
        
            # Compute the element stiffness matrix
            Ke = self.E*A_bar/Le*np.array(
                [[C**2, C*S, -C**2, -C*S],
                 [C*S, S**2, -C*S, -S**2],
                 [-C**2, -C*S, C**2, C*S],
                 [-C*S, -S**2, C*S, S**2]])
        
            # Create a list of the element variables for convenience
            elem_vars = [2*n1, 2*n1+1, 2*n2, 2*n2+1]
        
            # Add the element stiffness matrix to the global stiffness
            # matrix
            for i in xrange(4):
                for j in xrange(4):
                    K[elem_vars[i], elem_vars[j]] += Ke[i, j]
                    
        return K

    def assembleLoadVec(self):
        '''
        Create the load vector and populate the vector with entries
        '''

        f = np.zeros(len(self.xpos))
        for node in self.loads:
            # Add the values to the nodal locations
            f[2*node] += self.loads[node][0]
            f[2*node+1] += self.loads[node][1]

        return f

    def applyBCs(self, K, f):
        ''' 
        Apply the boundary conditions to the stiffness matrix and load
        vector
        '''

        # For each node that is in the boundary condition dictionary
        for node in self.bcs:
            uv_list = self.bcs[node]

            # For each index in the boundary conditions (corresponding to
            # either a constraint on u and/or constraint on v
            for index in uv_list:
                var = 2*node + index

                # Apply the boundary condition for the variable
                K[var, :] = 0.0
                K[:, var] = 0.0
                K[var, var] = 1.0
                f[var] = 0.0

        return

    def computeForces(self, A, u):
        '''
        Compute the forces in each of the truss members
        '''

        # Create the global stiffness matrix
        bar_forces = np.zeros(len(self.conn))

        # Loop over each element in the mesh
        index = 0
        for bar, A_bar in zip(self.conn, A):
            # Get the first and second node numbers from the bar
            n1 = bar[0]
            n2 = bar[1]

            # Compute the nodal locations
            xd = self.xpos[2*n2] - self.xpos[2*n1]
            yd = self.xpos[2*n2+1] - self.xpos[2*n1+1]
            Le = np.sqrt(xd**2 + yd**2)
            C = xd/Le
            S = yd/Le

            # Compute the hat displacements
            u1_hat = C*u[2*n1] + S*u[2*n1+1]
            u2_hat = C*u[2*n2] + S*u[2*n2+1]

            # Compute the strain
            epsilon = (u2_hat - u1_hat)/Le

            bar_forces[index] = self.E*A_bar*epsilon
            index += 1

        return bar_forces

    def printResult(self, x):
        '''
        Evaluate the derivative of the compliance and mass
        '''

        A = self.Area_scale*x

        # Evaluate compliance objective
        K = self.assembleMat(A)
        f = self.assembleLoadVec()
        self.applyBCs(K, f)

        # Solve the resulting linear system of equations
        u = np.linalg.solve(K, f)
        
        forces = self.computeForces(A, u)

        print 'Compliance:     %15.10f'%(0.5*np.dot(u, f))
        print 'Max strain:     %15.10f'%(max(forces/(self.E*A)))
        print 'Max abs strain: %15.10f'%(max(np.fabs(forces/(self.E*A))))
        print 'Min strain:     %15.10f'%(min(forces/(self.E*A)))

        return

    def fullyStressed(self, A, sigma_max, A_min):
        '''
        Perform the fully stress design procedure
        '''

        for i in xrange(100):
            # Evaluate compliance objective
            K = self.assembleMat(A)
            f = self.assembleLoadVec()
            self.applyBCs(K, f)

            # Solve the resulting linear system of equations
            u = np.linalg.solve(K, f)

            # Evaluate the forces
            forces = self.compute_forces(A, u)

            # Compute the mass
            mass = 0.0
            for bar, A_bar in zip(self.conn, A):
                # Get the first and second node numbers from the bar
                n1 = bar[0]
                n2 = bar[1]

                # Compute the nodal locations
                xd = self.xpos[2*n2] - self.xpos[2*n1]
                yd = self.xpos[2*n2+1] - self.xpos[2*n1+1]
                Le = np.sqrt(xd**2 + yd**2)

                mass += self.rho*A_bar*Le

            print mass

            for k in xrange(len(A)):
                A[k] = np.max([np.fabs(forces[k])/sigma_max, A_min])

        return A

    def plotTruss(self, A, tol=None, filename='opt_truss.pdf'):
        '''
        Plot the deformed and undeformed truss structure
        '''

        if tol is None:
            tol = 0.0

        fig = plt.figure(facecolor='w')

        # Evaluate compliance objective
        K = self.assembleMat(A)
        f = self.assembleLoadVec()
        self.applyBCs(K, f)

        # Solve the resulting linear system of equations
        u = np.linalg.solve(K, f)

        forces = self.computeForces(A, u)

        cm = plt.get_cmap('jet') 
        cNorm = colors.Normalize(vmin=min(forces), vmax=max(forces))
        scalarMap = cmx.ScalarMappable(norm=cNorm, cmap=cm)
        
        index = 0
        for bar in self.conn:
            n1 = bar[0]
            n2 = bar[1]

            if A[index] >= tol:
                plt.plot([self.xpos[2*n1], self.xpos[2*n2]], 
                         [self.xpos[2*n1+1], self.xpos[2*n2+1]], '-ko', 
                         linewidth=5*(A[index]/max(A)))
            index += 1

        plt.axis('equal')
        plt.savefig(filename)

        return

    def writeOutputFiles(self, A, show=False):
        '''
        Write out something to the screen
        '''

        if not hasattr(self, 'fig'):
            plt.ion()
            self.fig, self.ax = plt.subplots()
            plt.draw()

            # Draw a visualization of the truss
            index = 0
            max_A = max(A)
            self.lines = []

            for bar in self.conn:
                n1 = bar[0]
                n2 = bar[1]
                xv = [self.xpos[2*n1], self.xpos[2*n2]]
                yv = [self.xpos[2*n1+1], self.xpos[2*n2+1]]

                line, = self.ax.plot(xv, yv, '-ko', 
                                     linewidth=A[index])
                self.lines.append(line)
                index += 1
 
        else:
            # Set the value of the lines
            index = 0
            max_A = max(A)
            
            for bar in self.conn:
                plt.setp(self.lines[index], 
                         linewidth=5*(A[index]/max(A)))
                index += 1
 
        plt.axis('equal')
        plt.draw()

        return
