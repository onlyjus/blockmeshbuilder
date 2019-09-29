from .core import *

import numpy as np

headers = ['vertices', 'num_divisions', 'grading', 'baked_vertices', 'edges', 'faces', 'block_mask', 'vertex_mask', 'edge_mask', 'face_mask', 'zones']
formats = ['3f4','3u4','3O','O','3O','3O','?','?','3?','3?','U10']
struct_type = np.dtype({'names' : headers, 'formats' : formats})

init_pos = np.arange(3)

def wrapRadians(values):
	return values % (2*np.pi)

def np_cyl_to_cart(crds):
	ncrds = crds.copy()
	ncrds[...,0] = np.multiply(crds[...,0],np.cos(crds[...,1]))
	ncrds[...,1] = np.multiply(crds[...,0],np.sin(crds[...,1]))
	return ncrds

def np_cart_to_cyl(crds):
	ncrds = crds.copy()
	ncrds[...,0] = np.linalg.norm(crds[...,:-1],axis=-1)
	ncrds[...,1] = np.arctan2(crds[...,1],crds[...,0])
	return ncrds

DEFAULT_ZONE = 'DEFAULT'
class BaseBlockStruct(object):
	
	def __init__(self, x0, x1, x2, nd0, nd1, nd2, conv_func=cart_to_cart, zone=DEFAULT_ZONE):
		#Assume x0,x1,x2 are ascending 1D numpy arrays with dtype=np.float32, minimum 2 elements each
		#n0,n1,n2 are 1D numpy arrays of the number of divisions in each direction
		
		for x in [x0,x1,x2]:
			less_zero = np.diff(x) < 0.0
			if np.any(less_zero):
				print('ERROR -- A dimension array is in non-ascending order. Blocks will be inside out.')
				print(less_zero)
		
		shape = (x0.size,x1.size,x2.size)
		self.str_arr = np.empty(shape,dtype=struct_type)
		self.rshape = rshape = (shape[0]-1,shape[1]-1,shape[2]-1)
		
		#Initialize vertices
		X0,X1,X2 = np.meshgrid(x0,x1,x2,indexing='ij')
		
		vts = self['vertices']
		vts[...,0] = X0
		vts[...,1] = X1
		vts[...,2] = X2
		
		for ind in np.ndindex(self.shape):
			self['baked_vertices'][ind] = Vertex(vts[ind],conv_func)
		
		#Initialize number of divisions
		ND0,ND1,ND2 = np.meshgrid(nd0,nd1,nd2,indexing='ij')
		
		nds = self['num_divisions']
		nds[...,0] = ND0
		nds[...,1] = ND1
		nds[...,2] = ND2
		
		#Initialize grading
		self['grading'][:] = uniformGradingElement
		
		#Initialize edges and faces
		for s in range(3):
			roll_pos = np.roll(init_pos,s)
			
			d_edges = np.moveaxis(self['edges'][...,s],init_pos,roll_pos)
			d_faces = np.moveaxis(self['faces'][...,s],init_pos,roll_pos)
			d_vts = np.moveaxis(self['baked_vertices'],init_pos,roll_pos)
			
			for i in range(rshape[s]):
				for j in range(shape[(s+1)%3]):
					for k in range(shape[(s+2)%3]):
						d_edges[i,j,k] = ProjectionEdge(d_vts[i:i+2,j,k])
			
			for i in range(shape[s]):
				for j in range(rshape[(s+1)%3]):
					for k in range(rshape[(s+2)%3]):
						d_faces[i,j,k] = Face(d_vts[i,j:j+2,k:k+2])
		
		self['zones'][:] = zone
	
	def project_structure(self, dir, face_ind, geometry):
		
		#Get the subarray relevant to the face being projected
		roll_pos = np.roll(init_pos,dir)
		struct = np.moveaxis(self.str_arr,init_pos,roll_pos)[face_ind]
		rshape = np.roll(np.array(self.rshape),-dir)[1:]
		shape = struct.shape
		
		#Project vertices
		b_vts = struct['baked_vertices']
		vt_mask = struct['vertex_mask']
		for ind in np.ndindex(shape):
			if not vt_mask[ind]:
				b_vts[ind].proj_geom(geometry)
		
		#Project edges
		edges = np.roll(struct['edges'],-dir,axis=-1)[...,1:]
		edge_mask = np.roll(struct['edge_mask'],-dir,axis=-1)[...,1:]
		for j in range(shape[0]):
			for k in range(shape[1]):
				for s in range(2):
					edge = edges[j,k,s]
					if (not edge_mask[j,k,s]) and isinstance(edge, ProjectionEdge):
						edge.proj_geom(geometry)
		
		#Project faces
		faces = struct['faces'][...,dir]
		face_mask = struct['face_mask'][...,dir]
		for j in range(rshape[0]):
			for k in range(rshape[1]):
				if not face_mask[j,k]:
					faces[j,k].proj_geom(geometry)
	
	@staticmethod
	def _get_grading(gt):
		
		#Get relevant edges
		grd_arr = np.array([
			np.moveaxis(gt[...,s],s,0)[0].T for s in range(3)
		])
		
		#Get simplest grading type
		if np.all(grd_arr == uniformGradingElement):
			return uniformGrading
			
		elif np.all(np.array([grd_arr[s] == grd_arr[s,0,0] for s in range(3)])):
			return SimpleGrading(grd_arr[:,0,0])
			
		else:
			for gc in grd_arr:
				gc[1,0],gc[1,1] = gc[1,1],gc[1,0]
			
			return EdgeGrading(grd_arr.flatten())
	
	@staticmethod
	def _get_block_vertices(c_vs):
		return tuple((c_vs[0,0,0],c_vs[1,0,0],
			c_vs[1,1,0],c_vs[0,1,0],
			
			c_vs[0,0,1],c_vs[1,0,1],
			c_vs[1,1,1],c_vs[0,1,1]))
	
	def write(self,block_mesh_dict):
		
		#Reset block_mask edge
		bmask = self['block_mask']
		bmask[-1] = True
		bmask[:,-1] = True
		bmask[:,:,-1] = True
		
		for i in range(self.rshape[0]):
			for j in range(self.rshape[1]):
				for k in range(self.rshape[2]):
					
					if not bmask[i,j,k]:
						#Get subarray
						blockData = self[i:i+2,j:j+2,k:k+2]
						
						gt = blockData['grading'].copy()
						grading = self._get_grading(gt)
						
						nd = blockData['num_divisions'][0,0,0]
						
						vts = self._get_block_vertices(blockData['baked_vertices'])
						
						block_zone = blockData['zones'][0,0,0]
						
						block = HexBlock(vts, nd, block_zone, grading)
						block_mesh_dict.add_hexblock(block)
		
		#write relevant edges and faces
		shape = self.shape
		rshape = self.rshape
		
		for s in range(3):
			roll_pos = np.roll(init_pos,s)
			
			d_bmask = np.moveaxis(bmask,init_pos,roll_pos)
			d_edges = np.moveaxis(self['edges'][...,s],init_pos,roll_pos)
			d_faces = np.moveaxis(self['faces'][...,s],init_pos,roll_pos)
			
			for i in range(rshape[s]):
				for j in range(shape[(s+1)%3]):
					for k in range(shape[(s+2)%3]):
						edge = d_edges[i,j,k]
						
						if not edge.is_relevant():
							continue
						
						lmsk = d_bmask[i,max(j-1,0):j+1,max(k-1,0):k+1]
						if not np.all(lmsk):
							block_mesh_dict.add_edge(edge)
			
			for i in range(shape[s]):
				for j in range(rshape[(s+1)%3]):
					for k in range(rshape[(s+2)%3]):
						face = d_faces[i,j,k]
						
						if not face.is_projected():
							continue
						
						lmsk = d_bmask[max(i-1,0):i+1,j,k]
						if not np.all(lmsk):
							block_mesh_dict.add_face(face)
	
	#Default to underlying structured array
	def __getattr__(self, name):
		return getattr(self.str_arr, name)
	
	def __getitem__(self, key):
		return self.str_arr[key]


class CartBlockStruct(BaseBlockStruct):
	pass


class TubeBlockStruct(BaseBlockStruct):
	
	def __init__(self, rs, ts, zs, nr, nt, nz, zone='', is_complete=False):
		
		if np.any(rs < 0):
			print(f'WARNING -- Negative values detected in TubeBlockStruct rs array. This could yield unexpected results')
		
		if is_complete and ~np.isclose(wrapRadians(ts[0]),wrapRadians(ts[-1])):
			print(f'WARNING -- TubeBlockStruct in zone {zone} is marked as complete, while the first and last angles are unequal; make sure these are separated by 2*pi')
		
		BaseBlockStruct.__init__(self, rs, ts, zs, nr, nt, nz, cyl_to_cart, zone)
		
		b_vts = self['baked_vertices']
		edges = self['edges']
		faces = self['faces']
		rshape = self.rshape
		
		if is_complete:
			b_vts[:,-1] = b_vts[:,0]
		
		self.is_full = np.isclose(rs[0],0.)
		
		#Re-assign vertices, edges, and faces at the axis of the tube
		if self.is_full:
			b_vts[0] = b_vts[0,0]
			self['face_mask'][0,...,0] = True
			self['edge_mask'][0,...,1] = True
			
			for j in range(rshape[1]+1):
				for k in range(rshape[2]+1):
					edges[0,j,k,0] = ProjectionEdge(b_vts[0:2,j,k])
			
			for j in range(rshape[1]+1):
				for k in range(rshape[2]):
					faces[0,j,k,1] = Face(b_vts[0:2,j,k:k+2])
		
		self.is_complete = is_complete
	
	def write(self, block_mesh_dict):
		
		shape = self.shape
		shp = tuple((shape[0],shape[1]-1,shape[2]))
		
		vts = self['vertices']
		b_vts = self['baked_vertices']
		
		isR0 = np.isclose(vts[0,...,0],0.)
		
		if self.is_full and not np.all(isR0):
			print(f'WARNING -- When initialized, the inner radii in TubeBlockStruct in zone {self.zone} were set to 0, but some were changed before writing. The nodes along the centerline of the tube may not be positioned as expected.')
		
		cyls = {}
		s_pt = Point([0,0,-1e5])
		e_pt = Point([0,0,1e5])
		for i,r in np.ndenumerate(np.unique(vts[...,0])):
			
			if np.isclose(r,0.):
				pass
			
			cyl = Cylinder(s_pt,e_pt,r,f'blockcyl-{i}')
			cyls[r] = cyl
			block_mesh_dict.add_geometry(cyl)
		
		#Mask axial and radial edges as well as circumferential faces so no redundant edges or faces are written to file
		if self.is_complete:
			self['edge_mask'][:,-1,:,[0,2]] = True
			self['face_mask'][:,-1,:,1] = True
		
		b_vts = self['baked_vertices']
		vertex_mask = self['vertex_mask']
		proj_rcrds = self['vertices'][...,0]
		
		for ind in np.ndindex(shp):
			if not (vertex_mask[ind] or np.isclose(proj_rcrds[ind],0.)):
				b_vts[ind].proj_geom(cyls[proj_rcrds[ind]])
		
		edges = self['edges']
		edge_mask = self['edge_mask']
		r_faces = self['faces'][...,0]
		r_face_mask = self['face_mask'][...,0]
		acrds = self['vertices'][...,1]
		
		#Test and see if the axial edges need to be projected
		a_edges = edges[...,2]
		a_edge_mask = edge_mask[...,2]
		c_edges = edges[...,1]
		c_edge_mask = edge_mask[...,1]
		
		for ind in np.ndindex(shape):
			
			a_edge = a_edges[ind]
			if (not a_edge_mask[ind]) and isinstance(a_edge, ProjectionEdge):
				nind = ((ind[0],ind[1],ind[2]+1))
				if a_edge.is_relevant() or (not np.allclose(acrds[ind],acrds[nind])):
					a_edge.proj_geom(cyls[proj_rcrds[ind]])
			
			#r_face = r_faces[ind]
			#if r_face and (not r_face_mask[ind]) and (not r_face.is_projected()):
			#	r_face.proj_geom(cyls[proj_rcrds[ind]])
			
			c_edge = c_edges[ind]
			if (not c_edge_mask[ind]) and isinstance(c_edge, ProjectionEdge):
				c_edge.proj_geom(cyls[proj_rcrds[ind]])
			
		BaseBlockStruct.write(self, block_mesh_dict)

dummy_vertex = Vertex(0,0,0)
dummy_edge = Edge([dummy_vertex]*2,name = 'dummy')

class CylBlockStructContainer(object):
	
	def __init__(self, rs, ts, zs, nr, nt, nz, zone='', inner_arc_comp=0.25, eighth_twist=False):
		
		self.tube_struct = TubeBlockStruct(rs, ts, zs, nr, nt, nz, zone=zone, is_complete=True)
		
		if np.isclose(rs[0],0.):
			print(f'ERROR -- CylBlockStructContainer in zone {zone} has an inner tube radius of {rs[0]}, such that an o-grid cannot be accomodated. Consider using TubeBlockStruct instead.')
		
		self.inner_arc_comp = inner_arc_comp
		Ng = ((ts.size-1) // 4) + 1 #Assume integer number of divisions
		
		xs = np.linspace(-rs[0],rs[0],Ng)
		ys = xs.copy()
		
		nx = nt[:Ng].copy()
		ny = nt[Ng:2*Ng].copy()
		
		self.core_struct = CartBlockStruct(xs, ys, zs, nx, ny, nz, zone=zone)
		
		cyl_vts = np_cart_to_cyl(self.core_struct['vertices'])
		
		#If the o-grid is to be rotated by 45 degrees
		if eighth_twist:
			cyl_vts[...,1] -= np.pi
		else:
			cyl_vts[...,1] -= 5/4*np.pi
		
		self.core_struct['vertices'][:] = np_cyl_to_cart(cyl_vts)
		
		core_b_vts = self.core_struct['baked_vertices']
		tube_b_vts = self.tube_struct['baked_vertices']
		
		#Connect the outer tube structure to the core
		tInds = np.arange(ts.size-1).reshape(4,Ng-1)
		
		if eighth_twist:
			tInds = np.roll(tInds,-(Ng-1)//2)
		
		for s in range(4):
			tube_b_vts[0,tInds[s],:] = np.rot90(core_b_vts,k=-s)[:-1,0,:]
		
		tube_b_vts[0,-1,:] = tube_b_vts[0,0,:]
	
	def write(self,block_mesh_dict):
		
		self.tube_struct['face_mask'][0,:,:,0] = True
		self.tube_struct['vertex_mask'][0,:,:] = True
		
		iac = self.inner_arc_comp
		
		if not np.isclose(iac,1.0):
			tube = self.tube_struct
			shape = tube.shape
			shp = tuple((shape[0],shape[1]-1,shape[2]))
			
			vts = tube['vertices'][0]
			b_vts = tube['baked_vertices'][0]
			edge_mask = tube['edge_mask'][0,...,1]
			tube['edges'][0,...,1:] = dummy_edge
			
			for ind in np.ndindex(shp[1:]):
				
				if edge_mask[ind]:
					continue
				
				end_vts = b_vts[ind[0]:ind[0]+2,ind[1]]
				
				new_pt = (end_vts[0] + end_vts[1])/2
				mid_crds = cart_to_cyl(new_pt.crds)
				str_crds = cart_to_cyl(end_vts[0].crds)
				end_crds = cart_to_cyl(end_vts[1].crds)
				
				if str_crds[1] > end_crds[1]:
					end_crds[1] += 2*np.pi
				
				sweep_angle = (end_crds[1] - str_crds[1])/2
				mid_crds[0] = str_crds[0]*(iac*np.cos(sweep_angle) + (1-iac))
				mid_pt = Point(mid_crds,cyl_to_cart)
				block_mesh_dict.add_edge(ArcEdge(end_vts,mid_pt))
		
		else:
			self.tube_struct['edge_mask'][0,:,:,[1,2]] = True
		
		self.tube_struct.write(block_mesh_dict)
		self.core_struct.write(block_mesh_dict)