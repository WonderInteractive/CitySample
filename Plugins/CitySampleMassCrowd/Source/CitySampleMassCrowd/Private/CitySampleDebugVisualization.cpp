// Copyright Epic Games, Inc. All Rights Reserved.

#include "CitySampleDebugVisualization.h"
#include "MassExecutionContext.h"
#include "MassCommonFragments.h"
#include "MassDebuggerSubsystem.h"
#include "MassRepresentationFragments.h"
#include "Engine/World.h"

namespace FCitySampleDebugVisualizationTraitHelper
{
	constexpr EMassEntityDebugShape LODToShapeMapping[] = {
		EMassEntityDebugShape::Capsule, // EMassLOD::High
		EMassEntityDebugShape::Cone, // EMassLOD::Medium
		EMassEntityDebugShape::Cylinder, // EMassLOD::Low
		EMassEntityDebugShape::Box, // EMassLOD::Off
		EMassEntityDebugShape::Box, // EMassLOD::Max
	};
	static_assert(sizeof(LODToShapeMapping) / sizeof(EMassEntityDebugShape) == int(EMassLOD::Max) + 1, "LODToShapeMapping must account for all EMassLOD values");
} // FCitySampleDebugVisualizationTraitHelper

//----------------------------------------------------------------------//
//  UCitySampleDebugVisProcessor
//----------------------------------------------------------------------//
UCitySampleDebugVisProcessor::UCitySampleDebugVisProcessor()
	: EntityQuery(*this)
{
	ExecutionOrder.ExecuteAfter.Add(UE::Mass::ProcessorGroupNames::UpdateWorldFromMass);
}

void UCitySampleDebugVisProcessor::ConfigureQueries(const TSharedRef<FMassEntityManager>& EntityManager)
{
	EntityQuery.AddRequirement<FMassRepresentationLODFragment>(EMassFragmentAccess::ReadOnly);
	EntityQuery.AddRequirement<FTransformFragment>(EMassFragmentAccess::ReadOnly);
}

void UCitySampleDebugVisProcessor::Execute(FMassEntityManager& EntityManager, FMassExecutionContext& ExecutionContext)
{
	UMassDebuggerSubsystem* Debugger = UWorld::GetSubsystem<UMassDebuggerSubsystem>(GetWorld());
	if (Debugger == nullptr || !Debugger->IsCollectingData())
	{
		return;
	}

	QUICK_SCOPE_CYCLE_COUNTER(UCitySampleDebugVisProcessor_Run);

	EntityQuery.ForEachEntityChunk(ExecutionContext, [this, Debugger](FMassExecutionContext& Context)
		{
			TConstArrayView<FTransformFragment> LocationList = Context.GetFragmentView<FTransformFragment>();
			TConstArrayView<FMassRepresentationLODFragment> RepresentationLODList = Context.GetFragmentView<FMassRepresentationLODFragment>();

			for (FMassExecutionContext::FEntityIterator EntityIt = Context.CreateEntityIterator(); EntityIt; ++EntityIt)
			{
				const FMassRepresentationLODFragment& RepresentationLOD = RepresentationLODList[EntityIt];
				Debugger->AddShape(FCitySampleDebugVisualizationTraitHelper::LODToShapeMapping[int(RepresentationLOD.LOD)], LocationList[EntityIt].GetTransform().GetLocation(), AgentRadiusToUse);
			}
		});

	Debugger->DataCollected();
}