// Copyright Epic Games, Inc. All Rights Reserved.

#include "MassCrowdUpdateISMVertexAnimationProcessor.h"
#include "MassVisualizationComponent.h"
#include "MassRepresentationSubsystem.h"
#include "MassEntityManager.h"
#include "MassExecutionContext.h"
#include "MassRepresentationFragments.h"
#include "MassCommonFragments.h"
#include "MassLODFragments.h"
#include "MassCrowdAnimationTypes.h"
#include "MassTrafficInstancePlaybackHelpers.h"
#include "MassCommonTypes.h"
#include "MassCrowdRepresentationSubsystem.h"

UMassCrowdUpdateISMVertexAnimationProcessor::UMassCrowdUpdateISMVertexAnimationProcessor()
{
	ExecutionOrder.ExecuteAfter.Add(UE::Mass::ProcessorGroupNames::Tasks);
}

void UMassCrowdUpdateISMVertexAnimationProcessor::ConfigureQueries(const TSharedRef<FMassEntityManager>& EntityManager)
{
	Super::ConfigureQueries(EntityManager);

	EntityQuery.AddRequirement<FCrowdAnimationFragment>(EMassFragmentAccess::ReadWrite);
}

void UMassCrowdUpdateISMVertexAnimationProcessor::Execute(FMassEntityManager& EntityManager, FMassExecutionContext& ExecutionContext)
{
	EntityQuery.ForEachEntityChunk(ExecutionContext, [](FMassExecutionContext& Context)
	{
		UMassRepresentationSubsystem* RepresentationSubsystem = Context.GetSharedFragment<FMassRepresentationSubsystemSharedFragment>().RepresentationSubsystem;
		check(RepresentationSubsystem);
		FMassInstancedStaticMeshInfoArrayView ISMInfo = RepresentationSubsystem->GetMutableInstancedStaticMeshInfos();

		TConstArrayView<FTransformFragment> TransformList = Context.GetFragmentView<FTransformFragment>();
		TArrayView<FMassRepresentationFragment> RepresentationList = Context.GetMutableFragmentView<FMassRepresentationFragment>();
		TConstArrayView<FMassRepresentationLODFragment> RepresentationLODList = Context.GetFragmentView<FMassRepresentationLODFragment>();
		TArrayView<FCrowdAnimationFragment> AnimationDataList = Context.GetMutableFragmentView<FCrowdAnimationFragment>();

		for (FMassExecutionContext::FEntityIterator EntityIt = Context.CreateEntityIterator(); EntityIt; ++EntityIt)
		{
			const FTransformFragment& TransformFragment = TransformList[EntityIt];
			const FMassRepresentationLODFragment& RepresentationLOD = RepresentationLODList[EntityIt];
			FMassRepresentationFragment& Representation = RepresentationList[EntityIt];
			FCrowdAnimationFragment& AnimationData = AnimationDataList[EntityIt];

			if (Representation.CurrentRepresentation == EMassRepresentationType::StaticMeshInstance)
			{
				UpdateISMTransform(Context.GetEntity(EntityIt), ISMInfo[Representation.StaticMeshDescHandle.ToIndex()]
					, TransformFragment.GetTransform(), Representation.PrevTransform, RepresentationLOD.LODSignificance, Representation.PrevLODSignificance);
				UpdateISMVertexAnimation(ISMInfo[Representation.StaticMeshDescHandle.ToIndex()], AnimationData, RepresentationLOD.LODSignificance, Representation.PrevLODSignificance);
			}
			Representation.PrevTransform = TransformFragment.GetTransform();
			Representation.PrevLODSignificance = RepresentationLOD.LODSignificance;
		}
	});
}

void UMassCrowdUpdateISMVertexAnimationProcessor::UpdateISMVertexAnimation(FMassInstancedStaticMeshInfo& ISMInfo, FCrowdAnimationFragment& AnimationData, const float LODSignificance, const float PrevLODSignificance, const int32 NumFloatsToPad /*= 0*/)
{
	FMassTrafficInstancePlaybackData InstanceData;
	UMassTrafficInstancePlaybackLibrary::AnimStateFromDataAsset(AnimationData.AnimToTextureData.Get(), AnimationData.AnimationStateIndex, InstanceData.CurrentState);
	InstanceData.CurrentState.GlobalStartTime = AnimationData.GlobalStartTime;
	InstanceData.CurrentState.PlayRate = AnimationData.PlayRate;
	ISMInfo.AddBatchedCustomData<FMassTrafficInstancePlaybackData>(InstanceData, LODSignificance, PrevLODSignificance, NumFloatsToPad);
}
