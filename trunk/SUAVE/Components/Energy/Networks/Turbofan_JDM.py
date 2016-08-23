# Turbofan_JDM.py
#
# Created:  Oct 2015, A. Variyar
# Modified: Jun 2016, T. MacDonald

# Based on the turbofan analysis done in
# Elements of Propulsion: Gas Turbines and Rockets
# Jack D. Mattingly

# ----------------------------------------------------------------------
#  Imports
# ----------------------------------------------------------------------

# suave imports
import SUAVE

# package imports
import numpy as np
import scipy as sp
import datetime
import time
import copy
from SUAVE.Core import Units

# python imports
import os, sys, shutil
from copy import deepcopy
from warnings import warn


from SUAVE.Core import Data
from SUAVE.Components import Component, Physical_Component, Lofted_Body
from SUAVE.Components.Propulsors.Propulsor import Propulsor


# ----------------------------------------------------------------------
#  Turbofan Network
# ----------------------------------------------------------------------

class Turbofan_JDM(Propulsor):

    def __defaults__(self):

        #setting the default values
        self.tag = 'Turbofan'
        self.number_of_engines = 1.0
        self.nacelle_diameter  = 1.0
        self.engine_length     = 1.0
        self.bypass_ratio      = 1.0
        self.surrogate         = 0
        self.surrogate_model   = None
        self.map_scale         = None

    _component_root_map = None




    def engine_out(self,state):


        temp_throttle = np.zeros(len(state.conditions.propulsion.throttle))

        # Assume throttle now set to 1
        for i in range(0,len(state.conditions.propulsion.throttle)):
            temp_throttle[i] = state.conditions.propulsion.throttle[i]
            state.conditions.propulsion.throttle[i] = 1.0


        # Determine thrust at this condition
        results = self.evaluate_thrust(state)

        # Record throttle data
        for i in range(0,len(state.conditions.propulsion.throttle)):
            state.conditions.propulsion.throttle[i] = temp_throttle[i]


        # Scale thrust to thrust generated by remaining engines
        results.thrust_force_vector = results.thrust_force_vector/self.number_of_engines*(self.number_of_engines-1)
        results.vehicle_mass_rate   = results.vehicle_mass_rate/self.number_of_engines*(self.number_of_engines-1)



        return results



    #Solve the offdesign system of equations






    def size(self,state):

        conditions = state.conditions



        self.thrust.bypass_ratio = self.bypass_ratio
        number_of_engines         = self.number_of_engines

        # Get sizing thrust per engine
        sizing_thrust = self.thrust.total_design/float(number_of_engines)

        results_nondim = self.engine_design(state)

        F_mdot0 = results_nondim.thrust_force_vector
        S = results_nondim.sfc

        mdot0 = sizing_thrust/F_mdot0

        self.reference.mdot0R = mdot0

        results = Data()

        results.thrust_force_vector = self.thrust.total_design
        results.vehicle_mass_rate   = mdot0
        results.sfc                 = S
        results.thrust_non_dim      = F_mdot0


        state_sls = Data()
        state_sls.conditions = conditions
        state_sls.conditions.propulsion = Data()
        state_sls.conditions.propulsion.throttle = np.atleast_1d(1.0)
        results_sls = self.evaluate_thrustt(state_sls,0.0)
        self.sealevel_static_thrust = results_sls.thrust_force_vector[0,0] / float(number_of_engines)

        self.sealevel_static_mass_flow = results_sls.vehicle_mass_rate[0,0] / float(number_of_engines)
        self.sealevel_static_sfc = 3600. * self.sealevel_static_mass_flow / 0.1019715 / self.sealevel_static_thrust

        #print "sls thrust ",self.sealevel_static_thrust

        return results







    def engine_design(self,state):

        # Components

        ram = self.ram

        #imports
        conditions = state.conditions

        #engine properties
        pi_d_max = self.inlet_nozzle.pressure_ratio

        Tt4 = self.combustor.turbine_inlet_temperature
        pi_cL = self.low_pressure_compressor.pressure_ratio
        pi_cH = self.high_pressure_compressor.pressure_ratio
        e_c = self.high_pressure_compressor.polytropic_efficiency

        e_cH = self.high_pressure_compressor.polytropic_efficiency
        e_cL = self.low_pressure_compressor.polytropic_efficiency

        pi_f = self.fan.pressure_ratio
        e_f = self.fan.polytropic_efficiency

        eta_b = self.combustor.efficiency
        h_pr  = self.combustor.fuel_data.specific_energy
        pi_b  = self.combustor.pressure_ratio

        eta_m = self.high_pressure_turbine.mechanical_efficiency
        e_t   = self.high_pressure_turbine.polytropic_efficiency

        e_tH = self.high_pressure_turbine.polytropic_efficiency
        e_tL = self.low_pressure_turbine.polytropic_efficiency


        aalpha = self.thrust.bypass_ratio

        pi_n = self.core_nozzle.pressure_ratio

        pi_fn = self.fan_nozzle.pressure_ratio


        #gas properties
        gamma_c = self.compressor_gamma
        gamma_t = self.turbine_gamma
        c_pc = self.compressor_cp
        c_pt = self.turbine_cp
        g_c  = 1.0

        # Freestream properties
        T0 = conditions.freestream.temperature
        p0 = conditions.freestream.pressure
        M0 = conditions.freestream.mach_number

        # Design run

        R_c = (gamma_c - 1.0)/gamma_c*c_pc

        R_t = (gamma_t - 1.0)/gamma_t*c_pt

        a0 = np.sqrt(gamma_c*R_c*g_c*T0)

        V0 = a0*M0

        tau_lamda = c_pt*Tt4/(c_pc*T0)


        # Ram

        ram = self.ram
        ram.pi_d_max = pi_d_max
        working_fluid = self.working_fluid
        working_fluid.R = R_c
        working_fluid.gamma = gamma_c
        ram.inputs.working_fluid = working_fluid
        ram(conditions)

        pi_r = ram.outputs.pi_r
        tau_r = ram.outputs.tau_r
        eta_r = ram.outputs.eta_r


        # Diffusor

        inlet_nozzle = self.inlet_nozzle
        inlet_nozzle.inputs.eta_r = eta_r
        inlet_nozzle(conditions)

        pi_d = inlet_nozzle.outputs.pi_d


        # Fan

        fan = self.fan
        working_fluid = self.working_fluid
        working_fluid.gamma = gamma_c
        fan.inputs.working_fluid = working_fluid
        fan(conditions)

        tau_f = fan.outputs.tau_f
        eta_f = fan.outputs.eta_f


        # Low Pressure Compressor

        low_pressure_compressor = self.low_pressure_compressor
        working_fluid = self.working_fluid
        working_fluid.gamma = gamma_c
        low_pressure_compressor.inputs.working_fluid = working_fluid

        low_pressure_compressor(conditions)

        tau_cL = low_pressure_compressor.outputs.tau
        eta_cL = low_pressure_compressor.outputs.eta


        # High Pressure Compressor

        high_pressure_compressor = self.high_pressure_compressor
        working_fluid = self.working_fluid
        working_fluid.gamma = gamma_c
        high_pressure_compressor.inputs.working_fluid = working_fluid

        high_pressure_compressor(conditions)

        tau_cH = high_pressure_compressor.outputs.tau
        eta_cH = high_pressure_compressor.outputs.eta


        # Combustor

        combustor = self.combustor
        combustor.inputs.tau_lambda = tau_lamda
        combustor.inputs.tau_f      = tau_f
        combustor.inputs.tau_r      = tau_r
        combustor.inputs.tau_cL     = tau_cL
        combustor.inputs.tau_cH     = tau_cH
        combustor.inputs.c_pc       = c_pc
        combustor(conditions)

        f = combustor.outputs.fuel_to_air_ratio


        # High Pressure Turbine

        high_pressure_turbine = self.high_pressure_turbine
        working_fluid       = self.working_fluid
        working_fluid.gamma = gamma_t
        high_pressure_turbine.inputs.working_fluid = working_fluid
        high_pressure_turbine.inputs.tau_r = tau_r
        high_pressure_turbine.inputs.tau_cL = tau_cL
        high_pressure_turbine.inputs.tau_cH = tau_cH
        high_pressure_turbine.inputs.tau_lambda = tau_lamda
        high_pressure_turbine.inputs.f = f
        high_pressure_turbine.inputs.aalpha = None

        high_pressure_turbine(conditions)

        tau_tH = high_pressure_turbine.outputs.tau_t
        pi_tH  = high_pressure_turbine.outputs.pi_t
        eta_tH = high_pressure_turbine.outputs.eta_t

        # Low Pressure Turbine

        low_pressure_turbine = self.low_pressure_turbine
        working_fluid       = self.working_fluid
        working_fluid.gamma = gamma_t
        low_pressure_turbine.inputs.working_fluid = working_fluid
        low_pressure_turbine.inputs.tau_r = tau_r
        low_pressure_turbine.inputs.tau_cL = tau_cL
        low_pressure_turbine.inputs.tau_tH = tau_tH
        low_pressure_turbine.inputs.tau_lambda = tau_lamda
        low_pressure_turbine.inputs.f = f
        low_pressure_turbine.inputs.aalpha = aalpha
        low_pressure_turbine.inputs.tau_f  = tau_f

        low_pressure_turbine(conditions)

        tau_tL = low_pressure_turbine.outputs.tau_t
        pi_tL  = low_pressure_turbine.outputs.pi_t
        eta_tL = low_pressure_turbine.outputs.eta_t


        # Core Nozzle

        core_nozzle = self.core_nozzle

        core_nozzle.inputs.gamma_c     = gamma_c
        core_nozzle.inputs.gamma_t     = gamma_t
        core_nozzle.inputs.pi_r        = pi_r
        core_nozzle.inputs.pi_d        = pi_d
        core_nozzle.inputs.pi_cL       = pi_cL
        core_nozzle.inputs.pi_cH       = pi_cH
        core_nozzle.inputs.pi_b        = pi_b
        core_nozzle.inputs.pi_tL       = pi_tL
        core_nozzle.inputs.pi_tH       = pi_tH
        core_nozzle.inputs.pi_n        = pi_n
        core_nozzle.inputs.pi_f        = pi_f
        core_nozzle.inputs.tau_lambda  = tau_lamda
        core_nozzle.inputs.tau_tH      = tau_tH
        core_nozzle.inputs.tau_tL      = tau_tL
        core_nozzle.inputs.R_c         = R_c
        core_nozzle.inputs.R_t         = R_t
        core_nozzle.inputs.c_pc        = c_pc
        core_nozzle.inputs.c_pt        = c_pt

        core_nozzle(conditions)

        P0_P9 = core_nozzle.outputs.P0_P9
        T9_T0 = core_nozzle.outputs.T9_T0
        V9_a0 = core_nozzle.outputs.V9_a0
        M9    = core_nozzle.outputs.M9


        # Fan Nozzle

        fan_nozzle = self.fan_nozzle

        fan_nozzle.inputs.gamma_c     = gamma_c
        fan_nozzle.inputs.pi_r        = pi_r
        fan_nozzle.inputs.pi_d        = pi_d
        fan_nozzle.inputs.pi_f        = pi_f
        fan_nozzle.inputs.pi_fn       = pi_fn
        fan_nozzle.inputs.tau_r       = tau_r
        fan_nozzle.inputs.tau_f       = tau_f

        fan_nozzle(conditions)

        P0_P19 = fan_nozzle.outputs.P0_P19
        T19_T0 = fan_nozzle.outputs.T19_T0
        V19_a0 = fan_nozzle.outputs.V19_a0
        M19    = fan_nozzle.outputs.M19

        # Thrust calculation

        thrust = self.thrust
        thrust.inputs.aalpha  = aalpha
        thrust.inputs.f       = f
        thrust.inputs.V9_a0   = V9_a0
        thrust.inputs.T9_T0   = T9_T0
        thrust.inputs.P0_P9   = P0_P9
        thrust.inputs.R_t     = R_t
        thrust.inputs.gamma_c = gamma_c
        thrust.inputs.V19_a0  = V19_a0
        thrust.inputs.T19_T0  = T19_T0
        thrust.inputs.P0_P19  = P0_P19
        thrust.inputs.R_c     = R_c
        thrust.inputs.a0      = a0 # consider changing this with other ram update

        thrust(conditions)

        F_mdot0 = thrust.outputs.mass_specific_thrust
        S       = thrust.outputs.specific_fuel_consumption


        #reference values store
        reference = Data()

        reference.M0R = M0
        reference.T0R = T0
        reference.P0R = p0

        reference.tau_rR = tau_r
        reference.pi_rR = pi_r
        reference.Tt4R = Tt4

        reference.pi_dR = pi_d
        reference.pi_fR = pi_f
        reference.pi_cLR = pi_cL
        reference.pi_cHR = pi_cH

        reference.tau_fR = tau_f
        reference.tau_cHR = tau_cH
        reference.tau_tLR = tau_tL
        reference.tau_cLR = tau_cL
        reference.tau_tHR = tau_tH

        reference.alphaR = aalpha
        reference.M9R = M9
        reference.M19R = M19
        reference.mdot0R  = 1.0 #mdot0

        reference.tau_lamdaR = tau_lamda


        reference.pi_tH = pi_tH
        reference.pi_tL = pi_tL
        reference.pi_tLR = pi_tL


        reference.eta_f = eta_f
        reference.eta_cL = eta_cL
        reference.eta_cH = eta_cH
        reference.eta_tL = eta_tL
        reference.eta_tH  = eta_tH

        reference.P0_P9 = P0_P9

        reference.P0_P19 = P0_P19

        self.reference = reference






        results = Data()
        results.thrust_force_vector = F_mdot0
        results.vehicle_mass_rate   = 1.0
        results.sfc                 = S


        return results









    def evaluate_thrust(self,state,engine_efficiency=None):

        #imports
        conditions = state.conditions
        reference = self.reference
        throttle = conditions.propulsion.throttle

        #freestream properties
        T0 = conditions.freestream.temperature
        p0 = conditions.freestream.pressure
        M0 = conditions.freestream.mach_number

        F = np.zeros([len(T0),3])
        mdot0 = np.zeros([len(T0),1])
        S  = np.zeros(len(T0))
        F_mdot0 = np.zeros(len(T0))


        # setup conditions
        conditions_eval = SUAVE.Analyses.Mission.Segments.Conditions.Aerodynamics()

        state_eval = Data()

        for ieval in range(0,len(M0)):

            # freestream conditions

            conditions_eval.freestream.altitude           = np.atleast_1d(10.)
            conditions_eval.freestream.mach_number        = np.atleast_1d(M0[ieval])

            conditions_eval.freestream.pressure           = np.atleast_1d(p0[ieval][0])
            conditions_eval.freestream.temperature        = np.atleast_1d(T0[ieval][0])

            # propulsion conditions
            conditions_eval.propulsion.throttle           =  np.atleast_1d(throttle[ieval])


            state_eval.conditions = conditions_eval
            results_eval = self.evaluate_thrustt(state_eval,engine_efficiency)

            F[ieval][0] = results_eval.thrust_force_vector
            mdot0[ieval][0] = results_eval.vehicle_mass_rate
            S[ieval] = results_eval.sfc
            F_mdot0[ieval] = results_eval.thrust_non_dim




        results = Data()
        results.thrust_force_vector = F
        results.vehicle_mass_rate   = mdot0
        results.sfc                 = S
        results.thrust_non_dim      = F_mdot0
        results.offdesigndata = results_eval.offdesigndata


        return results


    def evaluate_thrustt(self,state,delta_Tt4,engine_efficiency=None):

        #imports
        conditions = state.conditions
        reference = self.reference
        throttle = conditions.propulsion.throttle
        number_of_engines         = self.number_of_engines

        #freestream properties
        T0 = conditions.freestream.temperature
        p0 = conditions.freestream.pressure
        M0 = conditions.freestream.mach_number
        #a0 = conditions.freestream.speed_of_sound

        #engine properties
        Tt4 = self.combustor.turbine_inlet_temperature

        pi_d_max = self.inlet_nozzle.pressure_ratio
        pi_b  = self.combustor.pressure_ratio
        pi_tH  = reference.pi_tH
        pi_n = self.core_nozzle.pressure_ratio
        pi_fn = self.fan_nozzle.pressure_ratio

        tau_tH  = reference.tau_tHR

        eta_f = reference.eta_f
        eta_cL = reference.eta_cL
        eta_cH = reference.eta_cH
        eta_b = self.combustor.efficiency
        eta_mH = self.high_pressure_turbine.mechanical_efficiency
        eta_mL = self.low_pressure_turbine.mechanical_efficiency

        e_cH = self.high_pressure_compressor.polytropic_efficiency
        e_cL = self.low_pressure_compressor.polytropic_efficiency
        e_f = self.fan.polytropic_efficiency
        #eta_tL = reference.eta_tL
        #eta_tH = reference.eta_tH

        #gas properties
        gamma_c = self.compressor_gamma
        gamma_t = self.turbine_gamma
        #c_pc = 0.24*778.16 #1004.5
        #c_pt = 0.276*778.16 #004.5
        #g_c  = 32.174

        c_pc = 1004.5
        c_pt = 1004.5
        g_c  = 1.0


        h_pr  = self.combustor.fuel_data.specific_energy #18400.0 #self.combustor.fuel_data.specific_energy


        #reference conditions

        M0R  = reference.M0R
        T0R = reference.T0R
        P0R = reference.P0R

        tau_rR = reference.tau_rR
        pi_rR = reference.pi_rR

        Tt4R = reference.Tt4R

        pi_dR = reference.pi_dR
        pi_fR = reference.pi_fR
        pi_cLR = reference.pi_cLR
        pi_cHR = reference.pi_cHR
        pi_tL  = reference.pi_tL
        tau_fR = reference.tau_fR
        #pi_f = reference.pi_fR
        tau_cHR = reference.tau_cHR
        tau_tLR = reference.tau_tLR
        alphaR = reference.alphaR
        M9R = reference.M9R
        M19R = reference.M19R

        mdot0R = reference.mdot0R
        tau_cLR = reference.tau_cLR
        pi_tLR = reference.pi_tLR
        tau_lamdaR = reference.tau_lamdaR
        eta_tL = reference.eta_tL
        eta_tH = reference.eta_tH
        #P0_P19 = reference.P0_P19
        #P0_P9  = reference.P0_P9
        #Tt4_min = self.combustor.Tt4_min
        #Tt4_max = self.combustor.Tt4_max


        #tau_fR = reference.tau_fR
        #tau_cLR = reference.tau_cLR
        #tau_tHR = reference.tau_tHR

        #tau_lamdaR = reference.tau_lamdaR
        #pi_tH = reference.pi_tH
        #pi_tL = reference.pi_tL


        #throttle to turbine inlet temperature

        #Tt4 = Tt4*throttle


        #Mattingly 8.52 a-j

        # Compressor and turbine gas constant values
        R_c = (gamma_c - 1.0)*c_pc/gamma_c
        R_t = (gamma_t - 1.0)*c_pt/gamma_t

        # Ram values
        a0 = np.sqrt(gamma_c*R_c*g_c*T0)
        V0 = a0*M0
        tau_r = 1.0 + 0.5*(gamma_c-1.0)*(M0**2.)
        pi_r = tau_r**(gamma_c/(gamma_c-1.0))

        eta_r = np.ones(len(M0)) #1.0
        #if(M0 > 1.0):
        eta_r[M0 > 1.0] = 1.0 - 0.075*(M0[M0 > 1.0] - 1.0)**1.35

        pi_d = pi_d_max*eta_r

        #Tt4 = Tt4_min + throttle*Tt4_max

        tau_lamda = c_pt*Tt4/(c_pc*T0)


        #compurte the min allowable turbine temp

        #fan
        tau_f_i = pi_fR**((gamma_c-1.0)/(gamma_c*e_f))
        tau_cL_i = pi_cLR**((gamma_c-1.0)/(gamma_c*e_cL))
        tau_cH_i = pi_cHR**((gamma_c-1.0)/(gamma_c*e_cH))
        min_Tt4 = tau_r*tau_f_i*tau_cL_i*tau_cH_i*T0
        max_Tt4 = Tt4
        delta_Tt4 = max_Tt4 - min_Tt4



        Tt4 = Tt4 + delta_Tt4#*throttle #min_Tt4 + throttle*delta_Tt4

        #print "Tt4 : ",Tt4



        #initial values for iteration

        tau_tL = copy.deepcopy(tau_tLR)
        tau_fan = copy.deepcopy(tau_fR)
        tau_cL = copy.deepcopy(tau_cLR)
        #tau_tH  = tau_tHR


        pi_tL = pi_tLR
        pi_cL = pi_cLR


        #print "initial : ",alphaR,tau_fR

        tau_tL_prev = 1.0
        #8.57 a - o
        iteration = 0
        while (1):



            tau_cH = 1.0 + (Tt4/T0)/(Tt4R/T0R)*(tau_rR*tau_cLR*tau_fR)/(tau_r*tau_cL*tau_fan)*(tau_cHR-1.0)
            #tau_cH = 1.0 + (Tt4/T0)/(Tt4R/T0R)*(tau_rR*tau_cLR)/(tau_r*tau_cL)*(tau_cHR-1.0)

            pi_cH = (1.0 +eta_cH*(tau_cH-1.0))**(gamma_c/(gamma_c-1.0))

            pi_f = (1.0 + (tau_fan-1.0)*eta_f)**(gamma_c/(gamma_c-1.0))


            pt19_po = pi_r*pi_d*pi_f*pi_fn

            #pt19_p19 = (0.5*(gamma_c+1.0))**(gamma_c/(gamma_c-1.0))


            if(pt19_po<((0.5*(gamma_c+1.0))**(gamma_c/(gamma_c-1.0)))):

                pt19_p19 = pt19_po[0]

            else:

                pt19_p19 = (0.5*(gamma_c+1.0))**(gamma_c/(gamma_c-1.0))


            #pt19_p19[pt19_po<((0.5*(gamma_c+1.0))**(gamma_c/(gamma_c-1.0)))] = pt19_po[pt19_po<((0.5*(gamma_c+1.0))**(gamma_c/(gamma_c-1.0)))]


            M19 = np.sqrt(2.0/(gamma_c-1.0)*((pt19_p19)**((gamma_c-1.0)/gamma_c)-1.0))

            #pt9_po = pi_r*pi_d*pi_cL*pi_cH*pi_b*pi_tH*pi_tL*pi_n#*pi_f

            pt9_po = pi_r*pi_d*pi_cL*pi_cH*pi_b*pi_tH*pi_tL*pi_n*pi_f


            pt9_p9 = (0.5*(gamma_t+1.0))**(gamma_t/(gamma_t-1.0))

            #pt9_p9[pt9_po < ((0.5*(gamma_t+1.0))**(gamma_t/(gamma_t-1.0)))] = pt9_po[pt9_po < ((0.5*(gamma_t+1.0))**(gamma_t/(gamma_t-1.0)))]

            if(pt9_po < ((0.5*(gamma_t+1.0))**(gamma_t/(gamma_t-1.0)))):

                pt9_p9 = pt9_po[0]

            else:

                pt9_p9 = (0.5*(gamma_t+1.0))**(gamma_t/(gamma_t-1.0))



            M9 = np.sqrt(2.0/(gamma_t-1.0)*(((pt9_p9)**((gamma_t-1.0)/(gamma_t)))-1.0))


            mfp_m19 = MFP(M19,gamma_c,R_c,g_c)

            mfp_m19R = MFP(M19R,gamma_c,R_c,g_c) #0.5318 #MFP(M19R,gamma_c,R_c,g_c)


            #aalpha = alphaR*(pi_cLR*pi_cHR/pi_fR)/(pi_cL*pi_cH/pi_f)*np.sqrt((tau_lamda/(tau_r*tau_fan))/(tau_lamdaR/(tau_rR*tau_fR)))*mfp_m19/mfp_m19R

            aalpha = alphaR*(pi_cLR*pi_cHR/pi_fR)/(pi_cL*pi_cH/pi_f)*np.sqrt((tau_lamda/(tau_r*tau_fan))/(tau_lamdaR/(tau_rR*tau_fR)))*mfp_m19/mfp_m19R


            tau_fan = 1.0 + (tau_fR - 1.0)*((1.0-tau_tL)/(1.0-tau_tLR)*(tau_lamda/tau_r)/(tau_lamdaR/tau_rR)*(tau_cLR-1.0 + alphaR*(tau_fR-1.0))/(tau_cLR-1.0 + aalpha*(tau_fR-1.0)))

            tau_cL = 1.0 + (tau_fan-1.0)*(tau_cLR-1.0)/(tau_fR-1.0)

            pi_cL = (1.0 + eta_cL*(tau_cL-1.0))**(gamma_c/(gamma_c-1.0))

            tau_tL = 1.0 - eta_tL*(1.0-pi_tL**((gamma_t-1.0)/gamma_t))


            mfp_m9 = MFP(M9,gamma_t,R_t,g_c)

            mfp_m9R = MFP(M9R,gamma_t,R_t,g_c) #0.5224

            mfp_m9_ratio = mfp_m9R/mfp_m9

            pi_tL = pi_tLR*np.sqrt(tau_tL/tau_tLR)*mfp_m9_ratio


            iteration = iteration + 1


            temp_val = np.abs((tau_tL-tau_tL_prev)/tau_tL_prev)


            #print iteration,tau_tL,tau_fan,aalpha


            if(temp_val < 0.0001) or(iteration==20):
                break

            #if(iteration==10):
                #break

            tau_tL_prev = tau_tL





        #8.57a - 8.57 o


        mdot0 = mdot0R*(1+aalpha)/(1+alphaR)*(p0*pi_r*pi_d*pi_cL*pi_cH*pi_f)/(P0R*pi_rR*pi_dR*pi_cLR*pi_cHR*pi_fR)*np.sqrt(Tt4R/Tt4)

        #mdot0 = mdot0R*(1+aalpha)/(1+alphaR)*(p0*pi_r*pi_d*pi_cL*pi_cH)/(P0R*pi_rR*pi_dR*pi_cLR*pi_cHR)*np.sqrt(Tt4R/Tt4)



        #f = (tau_lamda - tau_r*tau_cL*tau_cH)/(h_pr*eta_b/(c_pc*T0) - tau_lamda)
        f = (tau_lamda - tau_fan*tau_r*tau_cL*tau_cH)/(h_pr*eta_b/(c_pc*T0) - tau_lamda)


        #Equation 8.52z - 8.52ag

        T9_T0 = (tau_lamda*tau_tH*tau_tL)/((pt9_p9)**((gamma_t-1.0)/gamma_t))*(c_pc/c_pt)

        V9_a0 = M9*np.sqrt(gamma_t*R_t*T9_T0/(gamma_c*R_c))

        T19_T0 = tau_r*tau_fan/((pt19_p19)**((gamma_c-1.0)/gamma_c))

        V19_a0 = M19*np.sqrt(T19_T0)

        #P0_P9 = ((0.5*(gamma_c + 1.0))**(gamma_c/(gamma_c-1.0)))/(pi_r*pi_d*pi_cL*pi_cH*pi_b*pi_tL*pi_tH*pi_n) #pif
        P0_P9 = ((0.5*(gamma_c + 1.0))**(gamma_c/(gamma_c-1.0)))/(pi_r*pi_d*pi_cL*pi_cH*pi_b*pi_tL*pi_tH*pi_n*pi_f) #pif

        #P0_P9[P0_P9>1.0] = 1.0


        if(P0_P9>1.0):
            P0_P9 = 1.0


        P0_P19 = ((0.5*(gamma_c + 1.0))**(gamma_c/(gamma_c-1.0)))/(pi_r*pi_d*pi_f*pi_fn)
        #P0_P19[P0_P19>1.0] = 1.0

        if(P0_P19>1.0):
            P0_P19 = 1.0


        F_mdot0 = 1.0/(1.0+aalpha)*a0/g_c*((1.0+f)*V9_a0 - M0 + (1.0+f)*R_t*T9_T0*(1-P0_P9)/(R_c*V9_a0*gamma_c)) + aalpha/(1.0+aalpha)*a0/g_c*(V19_a0 - M0 + T19_T0*(1-P0_P19)/(V19_a0*gamma_c))

        #print "F_mdot0",F_mdot0,mdot0,pi_f,aalpha

        S = f/((1+aalpha)*F_mdot0)*3600.0*2.20462/0.224809

        F = mdot0*F_mdot0

        N_NR_fan = np.sqrt((T0*tau_r)/(T0R*tau_rR)*(pi_f**((gamma_c-1.0)/gamma_c)-1.0)/(pi_fR**((gamma_c-1.0)/gamma_c)-1.0))


        N_NR_HP = np.sqrt((T0*tau_r*tau_cL/(T0R*tau_rR*tau_cLR)*(pi_cH**((gamma_c-1.0)/gamma_c)-1.0)/(pi_cHR**((gamma_c-1.0)/gamma_c)-1.0)))


        ##update the throttle equation
        #if( N_NR_HP/throttle < 1):
            #Tt4 = Tt4 + Tt4*N_NR_HP
        #elif (N_NR_HP/throttle > 1):
            #Tt4 = Tt4 - Tt4*N_NR_HP




        #Equation 8.52ai - 8.52ak

        eta_T = (a0**2.0)*((1.0+f)*(V9_a0**2.0) + aalpha*(V19_a0**2.0) - (1.0+aalpha)*M0**2.0)/(2.0*g_c*f*h_pr)

        eta_P = (2.0*g_c*V0*(1+aalpha)*F_mdot0)/((a0**2.0)*((1.0+f)*(V9_a0**2.0) + aalpha*(V19_a0**2.0) - (1.0+aalpha)*M0**2.0))

        eta_0 = eta_P*eta_T

        mdot_fuel = S*F*0.224808943/(2.20462*3600.)


        #print "number of engines : ",float(number_of_engines),F

        Tt2_t = tau_r*T0

        #print "condition : ",M0
        #print "thrust, sfc, eta_th, eta_prop, eta_overall, BPR, FPR, LPC, HPC, HPT, LPT, Tt4, Tt4/Tt2, mdot_air"
        #print F,S,eta_T,eta_P,eta_0,aalpha,pi_f,pi_cL,pi_cH,1.0/pi_tH,1.0/pi_tL,Tt4,Tt4/Tt2_t,mdot0

        Tt3 = T0*tau_r*tau_cL*tau_cH
        pt3 = p0*pi_cL*pi_cH

        offdesigndata = Data()

        offdesigndata.F = F
        offdesigndata.S = S
        offdesigndata.eta_T = eta_T
        offdesigndata.eta_P = eta_P
        offdesigndata.aalpha = aalpha
        offdesigndata.pi_f = pi_f
        offdesigndata.pi_cL = pi_cL
        offdesigndata.pi_cH = pi_cH
        offdesigndata.pi_tH = 1.0/ pi_tH
        offdesigndata.pi_tL = 1.0/pi_tL
        offdesigndata.Tt4 = Tt4
        offdesigndata.Tt4_Tt2 = Tt4/Tt2_t
        offdesigndata.mdot0 = mdot0
        offdesigndata.mdotf = mdot_fuel
        offdesigndata.Tt3 = Tt3
        offdesigndata.pt3 = pt3



        results = Data()
        results.thrust_force_vector = F*float(number_of_engines)#*throttle
        results.vehicle_mass_rate   = mdot_fuel*float(number_of_engines)#*throttle
        results.sfc                 = S
        results.thrust_non_dim      = F_mdot0
        results.offdesigndata       = offdesigndata
        results.N_HP                = N_NR_HP




        return results






    __call__ = evaluate_thrust #evaluate_thrust



def MFP(M,gamma,R,g_c):

    #gamma = 1.4
    #g_c = 1.0
    #R = 287.0
    mfp_val = np.sqrt(gamma*g_c/R)*M/((1.0+ 0.5*(gamma-1.0)*M*M)**(0.5*(gamma+1.0)/(gamma-1.0)))


    #mfp_val = gamma*M/(((1.0+ 0.5*(gamma-1.0)*M*M)**(0.5*(gamma+1.0)/(gamma-1.0)))*np.sqrt(gamma*g_c/R))


    return mfp_val